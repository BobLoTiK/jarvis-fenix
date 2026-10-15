"""Russian numeric understanding and speech normalization.

Only explicit numeric command slots are rewritten. No downloads, LLM calls,
background training, or access to user profiles. Dependencies load on first use.
"""


def analyze_command(text):
    from .input import analyze_command as analyze

    return analyze(text)


def prepare_speech(text):
    from .speech import prepare_speech as prepare

    return prepare(text)
