#!/usr/bin/env python3
"""Sign license/status.json from tools/revoked.txt.

    python tools\\publish_status.py

Reads the Ed25519 signing seed from dist\\ig_admin_key.igk (override with
--key), builds the payload from tools/revoked.txt, signs it, verifies the
result, and writes license/status.json.

THE SEED NEVER ENTERS THIS REPOSITORY. .gitignore already excludes *.igk;
do not add one, do not paste one into a file here.

--- The one detail that must not drift ---------------------------------------

The signature covers exactly

    json.dumps(payload, sort_keys=True, separators=(",", ":"))

encoded UTF-8. This was verified against the 2026-08-24 status file with the
public key, not assumed. Any other serialization -- a space after the colon,
unsorted keys, a trailing newline -- produces a file that EVERY client
rejects. Do not "tidy" the dumps call.

Requires: pynacl  (pip install pynacl)  or  cryptography.
"""

import argparse
import base64
import binascii
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

DEFAULT_KEY = os.path.join(REPO, "..", "dist", "ig_admin_key.igk")
REVOKED_TXT = os.path.join(HERE, "revoked.txt")
STATUS_JSON = os.path.join(REPO, "license", "status.json")

CANON = dict(sort_keys=True, separators=(",", ":"))


# --- signing backend ---------------------------------------------------------

def _backend():
    try:
        from nacl.signing import SigningKey  # type: ignore

        def sign(seed, message):
            sk = SigningKey(seed)
            return bytes(sk.sign(message).signature), bytes(sk.verify_key)

        def verify(pub, message, sig):
            from nacl.signing import VerifyKey  # type: ignore
            VerifyKey(pub).verify(message, sig)

        return sign, verify
    except ImportError:
        pass

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore
            Ed25519PrivateKey,
        )
        from cryptography.hazmat.primitives import serialization  # type: ignore

        def sign(seed, message):
            sk = Ed25519PrivateKey.from_private_bytes(seed)
            pub = sk.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            return sk.sign(message), pub

        def verify(pub, message, sig):
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore
                Ed25519PublicKey,
            )
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, message)

        return sign, verify
    except ImportError:
        pass

    sys.exit("Need pynacl or cryptography:  pip install pynacl")


# --- seed loading ------------------------------------------------------------

def load_seed(path):
    """Accept a raw 32-byte seed, base64, hex, or JSON with a 'seed' key.

    If a real .igk turns out to be some other shape, THIS is the function to
    adjust -- nothing else in the file cares how the seed arrived.
    """
    if not os.path.exists(path):
        sys.exit("No signing key at %s\n(use --key to point at it)" % path)

    raw = open(path, "rb").read()

    if len(raw) == 32:
        return raw

    text = raw.decode("utf-8", "replace").strip()

    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError:
            pass
        else:
            for field in ("seed", "key", "private", "sk"):
                if field in doc:
                    return load_seed_value(str(doc[field]))
            sys.exit("JSON key file has no 'seed' field: %s" % path)

    return load_seed_value(text)


def load_seed_value(text):
    text = text.strip().strip('"').strip("'")

    if len(text) == 64:
        try:
            return binascii.unhexlify(text)
        except (binascii.Error, ValueError):
            pass

    pad = text + "=" * (-len(text) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            seed = decoder(pad)
        except Exception:
            continue
        if len(seed) == 32:
            return seed
        if len(seed) == 64:      # seed || public key, as some libraries store it
            return seed[:32]

    sys.exit("Could not read a 32-byte Ed25519 seed out of that key file.")


# --- revocation list ---------------------------------------------------------

def load_revoked(path):
    """One license id per line. '#' comments and blank lines ignored."""
    if not os.path.exists(path):
        return []
    ids = []
    for line in open(path, "r", encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line and line not in ids:
            ids.append(line)
    return ids


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Sign and write license/status.json")
    ap.add_argument("--key", default=DEFAULT_KEY, help="path to ig_admin_key.igk")
    ap.add_argument("--revoked", default=REVOKED_TXT, help="path to revoked.txt")
    ap.add_argument("--out", default=STATUS_JSON, help="path to status.json")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    sign, verify = _backend()
    seed = load_seed(args.key)
    revoked = load_revoked(args.revoked)

    payload = {
        "format": 1,
        "updated": int(time.time()),
        "revoked": revoked,
    }

    message = json.dumps(payload, **CANON).encode("utf-8")
    sig, pub = sign(seed, message)
    verify(pub, message, sig)                      # never publish an unverified file

    doc = {"payload": payload, "sig": base64.b64encode(sig).decode("ascii")}
    text = json.dumps(doc, indent=1) + "\n"

    print("public key : %s" % binascii.hexlify(pub).decode("ascii"))
    print("             (must equal LICENSE_PUB_HEX in inspector_gadgets.py)")
    print("revoked    : %d" % len(revoked))
    for rid in revoked:
        print("             %s" % rid)
    print("updated    : %d  (%s UTC)" % (
        payload["updated"],
        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(payload["updated"])),
    ))

    if args.dry_run:
        print("\n--dry-run, nothing written\n")
        print(text)
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, args.out)
    print("wrote      : %s" % args.out)
    print("\nNow: git add license/status.json && git commit && git push")


if __name__ == "__main__":
    main()
