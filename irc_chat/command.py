import string
import typing


class Command:

    def __init__(self, command_name: str, *argv: str, **kwargs: str):
        self.command = command_name
        self.prefix = kwargs.get("command_prefix", "<")
        self.suffix = kwargs.get("command_suffix", ">")
        self.args = argv
        self.action = None
        # self.args = " ".join(f"${{v}}" for v in argv)

    def set_action(self, action: typing.Callable):
        self.action = action
        return self

    @property
    def __spaced_args(self):
        return " " + self.args_string if self.num_args > 0 else ""

    @property
    def num_args(self):
        return len(self.args)

    @property
    def args_string(self):
        if self.num_args == 0:
            return ""
        return " ".join(f"${{{v}}}" for v in self.args)

    @property
    def template_string(self):
        return f"{self.prefix}{self.command}{self.suffix}" + self.__spaced_args

    @property
    def template(self):
        return string.Template(self.template_string)

    def format(self, *args: str) -> str:
        if len(args) < self.num_args:
            raise ValueError(f"Not enough arguments for command {self.command}")
        a = dict(zip(self.args, args))
        return self.template.substitute(**a)

    def __str__(self):
        return self.template_string

    def add_arg(self, *argv: str):
        if len(argv) == 0:
            return self
        self.args += argv
        return self

    def is_format(self, message: str) -> bool:
        if not message.startswith(self.prefix):
            return False
        message = message[len(self.prefix):]
        if not message.startswith(self.command):
            return False
        message = message[len(self.command):]
        if not message.startswith(self.suffix):
            return False
        message = message[len(self.suffix) + (self.num_args > 0):]
        args = message.split(" ", self.num_args)
        if args[0] == "":
            args = args[1:]
        if len(args) < self.num_args:  # change from < to != if you want an exact command match
            return False
        return True

    def execute(self, message: str, *args):
        if not self.is_format(message):
            raise ValueError(f"Message {message} is not a valid format for command {self.command}")
        if self.action is None:
            raise ValueError(f"No action set for command {self.command}")
        return self.action(*args)

    def __call__(self, message: str, *args):
        return self.execute(message, *args)

    def __eq__(self, other):
        return self.template_string == other.template_string and self.args == other.args

    def get_args(self, message: str) -> typing.List[str]:
        if not self.is_format(message):
            raise ValueError(f"Message {message} is not a valid format for command {self.command}")
        message = message[len(self.prefix) + len(self.command) + len(self.suffix) + (self.num_args > 0):]
        return message.split(" ", self.num_args - 1)


commands: typing.Dict[str, Command]

commands = {
    "CONNECT": Command("connect", "name"),
    "NICK": Command("nick", "name"),
    "QUIT": Command("quit"),
    "DISCONNECT": Command("disconnect"),
    "LIST": Command("list"),
    "GET_USERS": Command("get_users"),
    "SET_MSG": Command("set_msg", "name"),
    "SET_MSG_ALL": Command("set_msg_all"),
    "GET_LIST_FILE": Command("get_list_file"),
    "DOWNLOAD": Command("download", "file_name", "out_file_name"),
    "PROCEED": Command("proceed"),
}

server_commands = {
    "SERVER_DOWNLOAD": Command("server_download", "out_file_path", "port"),
}

commands.update(server_commands)


def parse_command(message: str) -> typing.Union[Command, None]:
    for command in commands.values():
        if command.is_format(message):
            return command
    return None


def get_args(message: str) -> typing.List[str]:
    command = parse_command(message)
    if command is None:
        return []
    msg = message[len(command.prefix) + len(command.command) + len(command.suffix) + 1:]
    return msg.split(" ", command.num_args)
