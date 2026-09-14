"""Read the site's JavaScript the way a browser first does, and say no early.

There is no Node on this machine, so nothing here has ever parsed the .js files
before they went up. That is how assets/site.js came to sit in the working tree
with four raw line breaks inside string literals: a SyntaxError, which does not
break the form - it stops the ENTIRE file from running, so the nav, the status
chip and the storybook go with it. Nothing shows an error. The page just sits
there.

This is not a JavaScript parser and does not pretend to be. It catches the two
mistakes that an editing session actually makes and that cost the whole file:

    1. a string literal with a real line break inside it
    2. brackets that do not close

Run it before pushing:

    python tools\\check_js.py

It exits 0 when every file is clean, 1 when it is not, and names the line.
"""
import io
import os
import sys

BS = chr(92)          # a backslash, written this way so nothing can eat it
QUOTES = ('"', "'", "`")

# A slash starts a regular expression, rather than dividing, when the thing
# before it is an operator or an opening bracket. Anything else and it is
# division. This is the same heuristic every syntax highlighter uses.
BEFORE_REGEX = set("(,=:[!&|?{};+-*%~^<>") | {"return", "typeof", "instanceof",
                                              "in", "of", "new", "delete",
                                              "void", "case", "do", "else"}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILES = [
    os.path.join("assets", "site.js"),
    os.path.join("admin", "desk.js"),
    os.path.join("worker", "cxpaper-license.js"),
]


def last_token(src, i):
    """The last meaningful character before position i, and the word it ends."""
    j = i - 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return "", ""
    end = j + 1
    while j >= 0 and (src[j].isalnum() or src[j] == "_" or src[j] == "$"):
        j -= 1
    return src[end - 1], src[j + 1:end]


def check(path):
    """Return a list of (line, complaint)."""
    src = io.open(path, encoding="utf-8").read()
    problems = []
    stack = []
    i, n, line = 0, len(src), 1

    while i < n:
        ch = src[i]

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue

        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                if src[i] == "\n":
                    line += 1
                i += 1
            i += 2
            continue

        if ch == "/":
            prev_char, prev_word = last_token(src, i)
            if prev_char in BEFORE_REGEX or prev_word in BEFORE_REGEX:
                start = line
                i += 1
                in_class = False
                closed = False
                while i < n:
                    if src[i] == BS:
                        i += 2
                        continue
                    if src[i] == "[":
                        in_class = True
                    elif src[i] == "]":
                        in_class = False
                    elif src[i] == "/" and not in_class:
                        i += 1
                        closed = True
                        break
                    elif src[i] == "\n":
                        break
                    i += 1
                if not closed:
                    problems.append((start, "a regular expression that never closes"))
                continue
            i += 1
            continue

        if ch in QUOTES:
            start, quote = line, ch
            i += 1
            closed = False
            while i < n:
                if src[i] == BS:
                    if src[i + 1:i + 2] == "\n":
                        line += 1          # a deliberate continuation is legal
                    i += 2
                    continue
                if src[i] == quote:
                    i += 1
                    closed = True
                    break
                if src[i] == "\n":
                    if quote == "`":
                        line += 1          # backticks may span lines
                        i += 1
                        continue
                    break
                i += 1
            if not closed:
                problems.append(
                    (start, "a string opened with %s and never closed on that "
                            "line - a real line break inside it is a "
                            "SyntaxError and stops the whole file" % quote))
            continue

        if ch in "([{":
            stack.append((ch, line))
        elif ch in ")]}":
            want = {")": "(", "]": "[", "}": "{"}[ch]
            if not stack:
                problems.append((line, "a closing %s with nothing open" % ch))
            elif stack[-1][0] != want:
                opened, where = stack.pop()
                problems.append((line, "a %s closing the %s opened on line %d"
                                 % (ch, opened, where)))
            else:
                stack.pop()

        i += 1

    for opened, where in stack:
        problems.append((where, "a %s that is never closed" % opened))

    return sorted(problems)


def main():
    bad = 0
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            print("  ?  %s is not there" % rel)
            continue
        problems = check(path)
        if problems:
            bad += 1
            print("FAIL %s" % rel)
            for line, why in problems:
                print("       line %d: %s" % (line, why))
        else:
            print("  ok %s" % rel)

    print("")
    if bad:
        print("%d file(s) would not run in a browser. Nothing else on the page "
              "runs either when that happens." % bad)
        return 1
    print("All clear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
