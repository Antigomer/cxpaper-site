"""Put the license desk on Cloudflare, asking Chris for one thing at most.

Started by the "Set up license desk" shortcut on the Desktop. Nothing to type.

It checks the Cloudflare credential first. If the saved one still works it goes
straight on and deploys. If it does not - which is where this stalled, because
the saved one had stopped working and deploy_worker.py could only say so - it
opens the page where a new one is made, opens the file to paste it into, waits
for that file to be saved and closed, and then carries on by itself.

The credential is pasted into Notepad, by hand, and read from the file. It is
never typed into a chat window and never leaves this machine.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

TOKEN_FILE = r"C:\_CLAUDE\cf-token.txt"
TOKEN_PAGE = "https://dash.cloudflare.com/profile/api-tokens"
API = "https://api.cloudflare.com/client/v4"

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(HERE, "deploy_worker.py")

RULE = "-" * 68


def say(*lines):
    for line in lines:
        print(line)


def credential_lines():
    if not os.path.isfile(TOKEN_FILE):
        return []
    text = open(TOKEN_FILE, encoding="utf-8", errors="replace").read()
    return [l.strip() for l in text.splitlines() if l.strip()]


def works(token):
    """Does Cloudflare accept this as an API token?"""
    req = urllib.request.Request(
        API + "/user/tokens/verify",
        headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("success") is True
    except urllib.error.HTTPError:
        return False
    except Exception:
        return None          # no internet - a different problem entirely


def any_line_works():
    """True / False / None (no internet). Extra lines are tolerated because
    the file also holds the account id, which is not a credential."""
    offline = False
    for line in credential_lines():
        got = works(line)
        if got is True:
            return True
        if got is None:
            offline = True
    return None if offline else False


def ask_for_a_new_one():
    say("",
        RULE,
        "  Cloudflare needs a new password from you. It takes a minute.",
        RULE,
        "",
        "  Two windows are opening now.",
        "",
        "  1. In the web page, at the TOP under 'API Tokens':",
        "       Create Token",
        "       find 'Edit Cloudflare Workers'  ->  Use template",
        "",
        "     Then DELETE the row called 'Workers Routes' - the X at the",
        "     right of it. It is the only row that asks for a zone, and",
        "     cxpaper.com is not on Cloudflare (its DNS is at DreamHost,",
        "     pointing at GitHub Pages), so there is no zone to choose and",
        "     the page will not let you past while that row is there.",
        "",
        "     These three are the ones that matter - leave them alone:",
        "       Workers Scripts     Edit",
        "       Workers KV Storage  Edit",
        "       Account Settings    Read",
        "",
        "       Continue to summary  ->  Create Token",
        "",
        "     It then shows you a long line of letters and numbers.",
        "     That line is shown ONCE and never again. Copy it.",
        "",
        "  2. In the Notepad window:",
        "       put it on its own line at the bottom",
        "       leave the line that is already there alone",
        "       File -> Save, then close Notepad",
        "",
        "  This window carries on by itself the moment you close Notepad.",
        "")

    try:
        os.startfile(TOKEN_PAGE)
    except Exception:
        say("  Could not open the browser. The page is: " + TOKEN_PAGE)

    if not os.path.isfile(TOKEN_FILE):
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        open(TOKEN_FILE, "w", encoding="utf-8").close()

    say("  Waiting for you to close Notepad...")
    try:
        # Blocks until Notepad is closed, which is the signal to carry on.
        subprocess.call(["notepad.exe", TOKEN_FILE])
    except Exception as e:
        say("  Could not open Notepad (%s). The file is: %s" % (e, TOKEN_FILE))
        return False
    return True


def deploy():
    say("", RULE, "  Putting the license desk on Cloudflare...", RULE, "")
    return subprocess.call([sys.executable, DEPLOY])


def main():
    say("", "Construction Paper - license desk setup", "")

    state = any_line_works()

    if state is None:
        say("This computer cannot reach Cloudflare at the moment.",
            "Check the internet connection and start this again.",
            "")
        return 1

    if state:
        say("The Cloudflare password saved on this machine still works.",
            "Nothing needed from you.")
    else:
        if credential_lines():
            say("The Cloudflare password saved on this machine has stopped",
                "working. Cloudflare will not accept it any more, so a new",
                "one has to be made. That is the only thing holding this up.")
        else:
            say("There is no Cloudflare password saved on this machine yet.")
        if not ask_for_a_new_one():
            return 1
        if not any_line_works():
            say("",
                "That still is not a password Cloudflare accepts.",
                "",
                "The usual reason is that only part of the line was copied,",
                "or the page was left before Create Token was clicked.",
                "Start this again and it will walk through it once more.",
                "")
            return 1
        say("", "That one works. Carrying on.")

    code = deploy()
    say("")
    if code == 0:
        say(RULE,
            "  Done. The license desk is live with its new password.",
            "",
            "  The dashboard opens with the line in:",
            "      C:\\_CLAUDE\\cp-admin-token.txt",
            RULE)
    else:
        say(RULE,
            "  That did not finish. The message above says why.",
            RULE)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
