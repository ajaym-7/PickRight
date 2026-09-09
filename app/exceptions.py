class PollNotOpenError(Exception):
    pass


class InvalidOptionError(Exception):
    pass


class AlreadyVotedError(Exception):
    pass


class BallotIdConflictError(Exception):
    pass


class BallotStateMissingError(Exception):
    pass