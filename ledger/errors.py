class LedgerError(Exception):
    pass


class AmountPrecisionError(LedgerError, ValueError):
    pass


class CurrencyMismatchError(LedgerError, ValueError):
    pass


class UnknownCurrencyError(LedgerError, LookupError):
    pass


class UnbalancedPostingError(LedgerError, ValueError):
    pass


class UnbalancedJournalError(LedgerError):
    pass


class DuplicatePostingError(LedgerError):
    pass


class UnknownAccountError(LedgerError, LookupError):
    pass


class DuplicateAccountError(LedgerError):
    pass
