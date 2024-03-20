"""
CLI UI tools

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import sys

__all__ = ['is_interactive', 'ask', 'ask_yes_no', 'user_prompt']

# Would be better to check if a client is connected...
__interactive = hasattr(sys, 'ps1')

# Fake interactivity if needed.
user_interactive = None


def is_interactive():
    """
    Check if session is interactive
    """
    return user_interactive if user_interactive is not None else __interactive


def ask(question, choices=None, clab=None, cval=None, default=None, help=None, assume=True, multiline=False):
    """
    Ask a question, offering given choices. Can also work in non-interactive cases

    :param question: The question asked
    :param choices: List of strings representing choices
    :param clab: optional choice labels to print instead of choices
    :param cval: optional choice of values to return
    :param default: which of the choices to choose by default. If None, no default
    :param help: A help string that can be printed if the user enters "?"
    :param assume: if True (default) can work in non-interactive mode
    :return: the chosen element from choices or the corresponding value if choices is a dict
    """
    # Use values if choice keys are not specified
    if choices is None:
        keys = [str(v).lower() for v in cval]
    else:
        keys = choices

    # values=keys if not specified
    if cval is None:
        values = dict((k, k) for k in keys)
    else:
        values = dict((k, v) for k, v in zip(keys, cval))

    # labels=keys if not specified
    if clab is None:
        labels = dict((k, k) for k in keys)
    else:
        labels = dict((k, v) for k, v in zip(keys, clab))

    if default not in keys:
        RuntimeError(f'default {default} not part of choices.')

    # If not working interactive, accept all defaults and raise error for cases without default
    if not is_interactive():
        if not assume or default is None:
            raise RuntimeError("Interactive mode only.")
        return values[default]

    str_keys = [labels[k] if default != k else f'[{labels[k]}]' for k in keys]
    # Add '?' as a possible choice if a help string was provided
    if help is not None:
        str_keys += '?'

    if multiline:
        ch_str = '\n ' + '\n '.join(str_keys) + '\n'
    else:
        ch_str = '(' + ', '.join(str_keys) + ')'

    prompt = f'{question} {ch_str} '

    while True:
        r = input(prompt).lower().strip('\n ')
        if not r:
            if default is None:
                print('No default answer. You must enter a choice')
                continue
            return values[default]
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
            return values[picks[0]]
        elif r in keys:
            return values[r]


def user_prompt(question, default=None, help=None):
    """
    Ask user text input.
    """
    if help is not None:
        question += ' (? for help)'
    while True:
        r = input(question + ' ')
        if not r:
            if default is None:
                print('No default answer. Enter text.')
                continue
            return default
        if r == '?':
            if help is None:
                print('No help.')
                continue
            else:
                print(help)
                continue
        return r


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
    return ask(question, choices=['yes', 'no'], cval=[True, False], default=default, help=help)

