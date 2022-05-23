import sys


__all__ = ['_interactive', 'ask', 'ask_yes_no']

# Would be better to check if a client is connected...
__interactive = hasattr(sys, 'ps1')

# Fake interactivity if needed.
user_interactive = None


def _interactive():
    """
    Check if session is interactive
    """
    return user_interactive if user_interactive is not None else __interactive


def ask(question, choices=None, default=None, help=None, assume=True):
    """
    Ask a question, offering given choices. Can also work in non-interactive cases

    :param question: The question asked
    :param choices: possible answers. List or dict.
    :param default: which of the choices to choose by default. If None, no default
    :param help: A help string that can be printed if the user enters "?"
    :param assume: if True (default) can work in non-interactive mode
    :return: the chosen element from choices or the corresponding value if choices is a dict
    """
    # If input choices is a list, make a dict with keys equal to values
    if isinstance(choices, dict):
        keys = list(choices.keys())
    else:
        keys = choices
        choices = dict((k, k) for k in keys)

    # If not working interactive, accept all defaults and raise error for cases without default
    if not _interactive():
        if not assume or default is None:
            raise RuntimeError("Interactive mode only.")
        return choices[default]

    # Generate list of choices to display in the prompt
    str_keys = [k if default != k else ('[%s]' % k) for k in keys]
    ch_str = ', '.join(str_keys)

    # Add '?' as a possible choice if a help string was provided
    if help is not None:
        ch_str += ', ?'

    prompt = '%s (%s): ' % (question, ch_str)

    while True:
        r = input(prompt).lower()
        prompt = '%s %s:' % (question, ch_str)
        if not r:
            if default is None:
                print('No default answer. You must enter a choice')
                continue
            return choices[default]
        if r == '?':
            if help is None:
                print('No help.')
                continue
            else:
                print(help)
                continue
        picks = [k for k in keys if k.startswith(r)]
        if len(picks) == 0:
            print('Unrecognized choice.')
            continue
        elif len(picks) > 1 and r not in keys:
            print('Ambiguous choice.')
            continue
        elif len(picks) == 1:
            return choices[picks[0]]
        elif r in keys:
            return choices[r]


def ask_yes_no(question, yes_is_default=True, help=None):
    """
    Ask a yes/no question, return True for yes, False for no. Defaults to yes.

    :param question: The question asked
    :param yes_is_default: True by default. Can be False (no is default) or None (no default)
    :param help: Optional additional help printed if user types '?'
    :return: True or False
    """
    if yes_is_default is None:
        default = None
    else:
        default = 'yes' if yes_is_default else 'no'
    return ask(question, choices={'yes': True, 'no': False}, default=default, help=help)

