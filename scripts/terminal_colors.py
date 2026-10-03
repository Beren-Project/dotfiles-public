"""Shared ANSI presentation for config comparisons and public-sync reviews."""
import os


def color_enabled(mode, out):
    """NO_COLOR takes precedence over every mode, including always."""
    if 'NO_COLOR' in os.environ or mode == 'never':
        return False
    return mode == 'always' or getattr(out, 'isatty', lambda: False)()


class TerminalColors:
    """Style presentation only; preserve every character of the plain output."""
    STATUS = {
        'ADD': 32, 'CHANGE': 33, 'DELETE': 31, 'RMDIR': 35,
        'DIFFERENT': 33, 'MISSING': 31, 'SYMLINK': 31,
        'TYPE CONFLICT': 31, 'UNREADABLE': 31,
    }

    def __init__(self, enabled=False):
        self.enabled = enabled

    def paint(self, text, code):
        if not self.enabled or code is None:
            return text
        ending = '\r\n' if text.endswith('\r\n') else '\n' if text.endswith('\n') else ''
        body = text[:-len(ending)] if ending else text
        return f'\x1b[{code}m{body}\x1b[0m{ending}'

    def status(self, label):
        return self.paint(label, self.STATUS.get(label))

    def diff_line(self, line, index):
        # unified_diff emits two file headers first; subsequent prefixes are
        # structural markers, even when the payload itself resembles a header.
        if index < 2:
            code = (31, 32)[index]
        elif line.startswith('@@'):
            code = 36
        else:
            code = {'-': 31, '+': 32}.get(line[:1])
        return self.paint(line, code)
