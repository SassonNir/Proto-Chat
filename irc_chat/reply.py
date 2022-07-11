import typing

import command


class Reply:
    def __init__(self, reply_type: str = "RPL", reply_prefix: str = "<", reply_suffix: str = ">",
                 reply_message: str = "", reply_code: int = 0):
        self.reply_type = reply_type
        self.reply_prefix = reply_prefix
        self.reply_suffix = reply_suffix
        self.reply_message = reply_message
        self.reply_code = reply_code

    def set_code(self, code: int):
        self.reply_code = code
        return self

    def set_message(self, message: str):
        self.reply_message = message
        return self

    @property
    def __spaced_message(self):
        return " " + self.reply_message if self.reply_message else ""

    def __str__(self):
        return self.reply_prefix + self.reply_type + self.reply_suffix + self.__spaced_message

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        return str(self).encode(encoding, errors)

    def __bytes__(self):
        return self.encode()

    def is_base_format(self, message: str) -> bool:
        if not message.startswith(self.reply_prefix):
            return False
        message = message[len(self.reply_prefix):]
        if not message.startswith(self.reply_type):
            return False
        message = message[len(self.reply_type):]
        if not message.startswith(self.reply_suffix):
            return False
        return True

    def is_format(self, message: str, approximate: bool = False) -> bool:
        if not self.is_base_format(message):
            return False
        message = message[len(self.reply_prefix) + len(self.reply_type) + len(self.reply_suffix):]
        if message.startswith(" "):
            message = message[1:]
        return message == self.reply_message if not approximate else message.startswith(self.reply_message)

    def extract_message(self, message: str) -> str:
        if not self.is_base_format(message):
            return ""
        message = message[len(self.reply_prefix) + len(self.reply_type) + len(self.reply_suffix):]
        if message.startswith(" "):
            message = message[1:]
        return message

    def extract_args(self, message: str) -> str:
        if not self.is_format(message, approximate=True):
            return ""
        message = message[len(self.reply_prefix) + len(self.reply_type) + len(self.reply_suffix):]
        if message.startswith(" "):
            message = message[1:]
        message = message[len(self.reply_message):]
        if message.startswith(" "):
            message = message[1:]
        return message

    def with_message(self, message: str):
        return Reply(self.reply_type, self.reply_prefix, self.reply_suffix, message, self.reply_code)


base: dict[str, Reply] = {
    "REPLY": Reply("RPL", reply_code=0),
    "ERROR": Reply("ERR", reply_code=1),
    "OK": Reply("OK", reply_code=2),
}

replies = {
    "RPL_CONNECTED": "Connected to server",
    "RPL_WELCOME": "Welcome to the server",
    "RPL_DISCONNECTED": "Disconnected from server",
    "RPL_PRVTMSGON": "Private messages are now enabled",
    "RPL_PRVTMSGOFF": "Private messages are now disabled",
    "RPL_DOWNLOADSTART": "Download started",
    "RPL_DOWNLOADPORT": "Download port",
    "RPL_PROCEED": "Please proceed the download using the command " + command.commands["PROCEED"].template_string,
}

errors = {
    "ERR_NICKNAMEINUSE": "Nickname is already in use",
    "ERR_NOSUCHNICK": "User does not exist",
    "ERR_UNKNOWNCOMMAND": "Unknown command",
    "ERR_NONICKNAMEGIVEN": "No nickname given, please connect using the command " + command.commands[
        "CONNECT"].template_string,
    "ERR_FILENOTFOUND": "File not found",
}

replies = {k: base["REPLY"].with_message(v) for k, v in replies.items()}
errors = {k: base["ERROR"].with_message(v) for k, v in errors.items()}

all_replies = replies | errors


def parse_reply(message: str) -> typing.Union[Reply, None]:
    for reply in all_replies.values():
        if reply.is_format(message):
            return reply
    return None


def parse_base(message: str) -> typing.Union[Reply, None]:
    for reply in base.values():
        if reply.is_base_format(message):
            return reply.with_message(reply.extract_message(message))
    return None
