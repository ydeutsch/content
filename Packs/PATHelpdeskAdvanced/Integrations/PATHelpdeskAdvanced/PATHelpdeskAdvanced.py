import contextlib
from json import JSONDecodeError
from pathlib import Path
from pprint import pformat
from typing import Literal, NamedTuple
from collections.abc import Callable
from collections.abc import Sequence
from requests import Response

import demistomock as demisto
from CommonServerPython import *  # noqa: F401
from CommonServerUserPython import *  # noqa

VENDOR = "HelpdeskAdvanced"

FILTER_CONDITION_REGEX = re.compile(
    r"\A\"(?P<key>.*?)\" (?P<op>eq|gt|lt|ge|lt|sw|ne) (?P<value>(?:\".*?\"|null))\Z"
)
DATE_VALUE_REGEX = re.compile(r"/Date\((\d+)\)/")


class Field:
    def __init__(self, demisto_name: str) -> None:
        title_parts = []
        for part in demisto_name.split("_"):
            if part == "unread":
                title_parts.append("UnRead")
            elif part in {"id", "html"}:
                title_parts.append(part.upper())
            else:
                title_parts.append(part.title())

        self.demisto_name = demisto_name  # lower_case
        self.hda_name = "".join(title_parts)  # PascalCase


OBJECT_TYPE_ID = Field("object_type_id")
TICKET_STATUS_ID = Field("ticket_status_id")
TICKET_PRIORITY_ID = Field("ticket_priority_id")
TICKET_CLASSIFICATION_ID = Field("ticket_classification_id")
TICKET_TYPE_ID = Field("ticket_type_id")
OBJECT_DESCTIPTION = Field("object_description")
OBJECT_ENTITY = Field("object_entity")
CONTACT_ID = Field("contact_id")
SUBJECT = Field("subject")
PROBLEM = Field("problem")
SITE = Field("site")
ID = Field("id")
IS_NEW = Field("is_new")
EXPIRATION_DATE = Field("expiration_date")
FIRST_UPDATE_USER_ID = Field("first_update_user_id")
OWNER_USER_ID = Field("owner_user_id")
ASSIGNED_USER_ID = Field("assigned_user_id")
SOLUTION = Field("solution")
SERVICE_ID = Field("service_id")
LOCATION_ID = Field("location_id")
PROBLEM_HTML = Field("problem_html")
NEXT_EXPIRATION_ID = Field("next_expiration_id")
TASK_EFFORT = Field("task_effort")
SUPPLIER_ID = Field("supplier_id")
SOLUTION_HTML = Field("solution_html")
ESTIMATED_TASK_START_DATE = Field("estimated_task_start_date")
ACCOUNT_ID = Field("account_id")
MAIL_BOX_ID = Field("mail_box_id")
CLOSURE_DATE = Field("closure_date")
BILLED_TOKENS = Field("billed_tokens")
PARENT_TICKET_ID = Field("parent_ticket_id")
CUSTOMER_CONTRACT_ID = Field("customer_contract_id")
KNOWN_ISSUE = Field("known_issue")
LANGUAGE_ID = Field("language_id")
ASSET_ID = Field("asset_id")
DATE = Field("date")
URGENCY_ID = Field("urgency_id")
SCORE = Field("score")
ESTIMATED_TASK_DURATION = Field("estimated_task_duration")
SITE_UNREAD = Field("site_unread")
SOLICITS = Field("solicits")
CALENDAR_ID = Field("calendar_id")
LAST_EXPIRATION_DATE = Field("last_expiration_date")
NEXT_EXPIRATION_DATE = Field("next_expiration_date")
ASSIGNED_USER_OR_GROUP_ID = Field("next_user_or_group_id")
PARENT_OBJECT = Field("parent_object")
PARENT_OBJECT_ID = Field("parent_object_id")
TICKET_ID = Field("ticket_id")
TICKET_STATUS = Field("ticket_status")
TEXT = Field("text")
SITE_VISIBLE = Field("site_visible")
DESCRIPTION = Field("description")
TICKET_PRIORITY = Field("ticket_priority")
_PRIORITY = Field("priority")
_TICKET_SOURCE = Field("ticket_source")


ID_DESCRIPTION_COLUMN_NAMES = str([field.hda_name for field in (ID, DESCRIPTION)])


def safe_arg_to_number(argument: str | None, argument_name: str) -> int:
    # arg_to_number is typed as if it returns Optional[int], which causes mypy issues down the road.
    # this method solves them
    if (result := arg_to_number(argument)) is None:
        raise ValueError(f"cannot parse number from {argument_name}={argument}")
    return result


def parse_filter_conditions(strings: Sequence[str]) -> list[dict]:
    return [_parse_filter_condition(string) for string in strings]


def _parse_filter_condition(string: str) -> dict:
    if not (match := FILTER_CONDITION_REGEX.match(string)):
        raise DemistoException(
            f'Cannot parse {string}. Expected a phrase of the form "key" operator "value" or "key" operator null'
        )
    return {
        "property": match["key"],
        "op": match["op"],
        "value": None if ((value := match["value"]) == "null") else value.strip('"'),
    }


def create_params_dict(
    required_fields: tuple[Field, ...] = (),
    optional_fields: tuple[Field, ...] = (),
    **kwargs,
):
    result = {field.hda_name: kwargs[field.demisto_name] for field in required_fields}

    for field in optional_fields:
        if field.demisto_name in kwargs:
            result[field.hda_name] = kwargs[field.demisto_name]

    return result


class RequestNotSuccessfulError(DemistoException):
    def __init__(self, response: Response, attempted_action: str):
        json_response = {}
        with contextlib.suppress(JSONDecodeError):
            json_response = response.json()

        suffix = (
            f": {description}."
            if (description := json_response.get("result", {}).get("desc"))
            else "."
        )
        super().__init__(
            f"{attempted_action.capitalize()} failed{suffix}", res=response
        )


def map_id_to_description(response: dict) -> dict[str, str]:
    return {item[ID.hda_name]: item[DESCRIPTION.hda_name] for item in response["data"]}


def convert_response_dates(response: dict) -> dict:
    def fix_value(value: str) -> str | datetime:
        if (
            isinstance(value, str)
            and value
            and (match := DATE_VALUE_REGEX.match(value))
        ):
            return str(datetime.fromtimestamp(int(match[1][:-3])))
        return value

    def fix_recursively(value):  # no typing as the cases are complex and confuse mypy
        if isinstance(value, dict):
            return {k: fix_recursively(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [fix_recursively(v) for v in value]
        return fix_value(value)

    return fix_recursively(response)


class Client(BaseClient):
    def http_request(
        self,
        url_suffix: str,
        method: Literal["GET", "POST"],
        attempted_action: str,
        **kwargs,
    ) -> dict:
        print(
            f"Making {method} request to {self._base_url}{url_suffix}\n{pformat(kwargs)}"
        )
        response = self._http_request(
            method, url_suffix, resp_type="response", **kwargs
        )
        try:
            response_body = json.loads(response.text)
            print(f"Response: {pformat(response_body)}")
            if response_body["success"] is not True:  # request failed
                raise RequestNotSuccessfulError(response, attempted_action)
            return response_body

        except JSONDecodeError as e:
            raise ValueError(f"could not parse json from {response.text}") from e

    def __init__(
        self,
        base_url: str,
        verify: bool,
        proxy: bool,
        username: str,
        password: str,
    ):
        super().__init__(base_url=base_url, verify=verify, proxy=proxy)
        self._username = username
        self._password = password

        self.request_token: str | None = None
        self.token_expiry_utc: datetime | None = None

        self._login()  # sets request_token and token_expiry_utc

    def _login(self) -> None:
        # should only be called from __init__
        def generate_new_token() -> dict:
            return self.http_request(
                method="POST",
                url_suffix="Authentication/LoginEx",
                attempted_action="logging in using username and password",
                params={"username": self._username, "password": self._password},
                headers={"Content-Type": "multipart/form-data"},
            )

        def generate_request_token(refresh_token: str) -> dict:
            return self.http_request(
                method="POST",
                url_suffix="Authentication/RefreshToken",
                params={"token": refresh_token},
                attempted_action="generating request token using refresh token",
                headers={"Content-Type": "multipart/form-data"},
            )

        # Check integration context
        integration_context = demisto.getIntegrationContext()
        print(f"integration_context = {pformat(integration_context)}")
        refresh_token = integration_context.get("refresh_token")
        raw_token_expiry_utc: str | None = integration_context.get("token_expiry_utc")

        # Do we need to log in again, or can we just refresh?
        if (
            raw_token_expiry_utc
            and (token_expiry_utc := dateparser.parse(raw_token_expiry_utc))
            and token_expiry_utc > (datetime.utcnow() + timedelta(seconds=5))
        ):
            try:
                print("refresh token is valid, using it to generate a request token")
                response = generate_request_token(refresh_token)

            except RequestNotSuccessfulError:
                print(
                    "failed using refresh token, getting a new one using username and password"
                )
                response = generate_new_token()

        else:
            print(
                "refresh token expired or missing, logging in with username and password"
            )
            response = generate_new_token()

        self.request_token = response["requestToken"]
        self.refresh_token = response["refreshToken"]
        self.token_expiry_utc = datetime.utcnow() + timedelta(
            seconds=response["expiresIn"]
        )

        self._headers = {"Authorization": f"Bearer {self.request_token}"}
        demisto.setIntegrationContext(
            integration_context
            | {
                "refresh_token": self.refresh_token,
                "request_token": self.request_token,  # TODO is it used?
                "token_expiry_utc": str(self.token_expiry_utc),
            }
        )
        demisto.debug(f"login complete. {self.token_expiry_utc=}")

    def create_ticket(self, **kwargs) -> dict:
        required_fields = (
            OBJECT_TYPE_ID,
            TICKET_STATUS_ID,
            TICKET_PRIORITY_ID,
        )
        optional_fields = (
            OBJECT_DESCTIPTION,
            TICKET_CLASSIFICATION_ID,
            TICKET_TYPE_ID,
            CONTACT_ID,
            SUBJECT,
            PROBLEM,
            SITE,
        )
        data = create_params_dict(
            required_fields,
            optional_fields,
            **kwargs,
        )

        return self.http_request(
            "WSC/Set",
            "POST",
            data={"entity": "Ticket", "data": data},
            attempted_action="creating ticket",
        )

    def list_tickets(self, **kwargs) -> dict:
        columns = str(
            [
                field.hda_name
                for field in (
                    OBJECT_DESCTIPTION,
                    OBJECT_ENTITY,
                    SOLUTION,
                    TICKET_CLASSIFICATION_ID,
                    SERVICE_ID,
                    PROBLEM_HTML,
                    CONTACT_ID,
                    NEXT_EXPIRATION_ID,
                    TASK_EFFORT,
                    ID,
                    SUPPLIER_ID,
                    SOLUTION_HTML,
                    IS_NEW,
                    EXPIRATION_DATE,
                    LOCATION_ID,
                    ESTIMATED_TASK_START_DATE,
                    FIRST_UPDATE_USER_ID,
                    ACCOUNT_ID,
                    MAIL_BOX_ID,
                    CLOSURE_DATE,
                    BILLED_TOKENS,
                    TICKET_TYPE_ID,
                    OWNER_USER_ID,
                    PARENT_TICKET_ID,
                    CUSTOMER_CONTRACT_ID,
                    LANGUAGE_ID,
                    KNOWN_ISSUE,
                    ASSET_ID,
                    DATE,
                    URGENCY_ID,
                    SCORE,
                    SUBJECT,
                    ESTIMATED_TASK_DURATION,
                    SOLICITS,
                    SITE,
                    CALENDAR_ID,
                    LAST_EXPIRATION_DATE,
                    SITE_UNREAD,
                    PROBLEM,
                    NEXT_EXPIRATION_DATE,
                    ASSIGNED_USER_OR_GROUP_ID,
                )
            ]
        )

        params: dict[str, str | list | int | None] = {
            "entity": "Ticket",
            "filter": None,
            "columnExpressions": columns,
            "columnNames": columns,
            "start": safe_arg_to_number(kwargs.get("start", 0), "start"),
            "limit": safe_arg_to_number(kwargs["limit"], "limit"),
        }

        if filter_params := parse_filter_conditions(kwargs.get("filter") or ()):
            params["filter"] = filter_params
        return self.http_request(
            url_suffix="WSC/Projection",
            method="POST",
            attempted_action="listing tickets",
            params=params,
        )

    def add_ticket_attachment(self, entry_ids: list[str], **kwargs) -> dict:
        return self.http_request(
            url_suffix="Ticket/UploadNewAttachment",
            method="POST",
            attempted_action="uploading a new attachment",
            params={
                "entity": "Ticket",
                "entityID": kwargs["ticket_id"],
            }
            | {  # maps "TicketAttachment_i+1" to file content
                f"TicketAttachment_{i+1}": Path(
                    demisto.getFilePath(entry_id)["path"]
                ).read_text()
                for i, entry_id in enumerate(entry_ids)
            },
        )

    def list_ticket_attachments(self, **kwargs) -> dict:
        ticket_id = kwargs["ticket_id"]
        params = {
            "entity": "Attachments",
            "start": 0,  # TODO necessary?
            "limit": safe_arg_to_number(kwargs["limit"], "limit"),
            "filter": parse_filter_conditions(
                (
                    f'"{PARENT_OBJECT.hda_name}" eq "Ticket"',
                    f'"{PARENT_OBJECT_ID.hda_name}" eq "{ticket_id}"',
                )
            ),
        }

        return self.http_request(
            url_suffix="/WSC/List",
            method="POST",
            params=params,
            attempted_action="listing ticket attachments",
        )

    def add_ticket_comment(self, **kwargs) -> dict:
        return self.http_request(
            url_suffix="WSC/Set",
            method="POST",
            data={
                "entity": "TicketConversationItem",
                "data": {
                    TICKET_ID.hda_name: kwargs[TICKET_ID.demisto_name],
                    TEXT.hda_name: kwargs["comment"],
                    SITE_VISIBLE.hda_name: kwargs[SITE_VISIBLE.demisto_name],
                    OBJECT_TYPE_ID.hda_name: "90",  # hardcoded by design. 90 marks ObjectTypeIDField
                },
            },
            attempted_action="adding ticket command",
        )

    def list_ticket_statuses(self, **kwargs) -> dict:
        return self.http_request(
            url_suffix="WSC/Projection",
            method="POST",
            attempted_action="listing ticket statuses",
            data={
                "entity": TICKET_STATUS.hda_name,
                "start": 0,
                "limit": safe_arg_to_number(kwargs["limit"], "limit"),
                "columnNames": ID_DESCRIPTION_COLUMN_NAMES,
                "columnExpressions": ID_DESCRIPTION_COLUMN_NAMES,
            },
        )

    def change_ticket_status(
        self, status: str, ticket_id: str, note: str | None
    ) -> dict:
        statuses_to_id = map_id_to_description(
            self.list_ticket_statuses(limit=1000)
        )  # TODO 1000?

        # Find status ID matching the selected status
        if (status_id := statuses_to_id.get(status)) is None:
            demisto.debug(f"status to id mapping: {statuses_to_id}")
            raise DemistoException(
                f"Cannot find id for {status}."
                f"See debug log for the {len(statuses_to_id)} status mapping options found."
            )

        params = {
            "ticketID": ticket_id,
            "ticketStatusID": status_id,
        }

        if note:
            params["note"] = note

        return self.http_request(
            url_suffix="Ticket/DoChangeStatus",
            method="POST",
            attempted_action="changing ticket status",
            params=params,
        )

    def list_ticket_priorities(self) -> dict:
        return self.http_request(
            url_suffix="WSC/Projection",
            method="POST",
            attempted_action="listing ticket priorities",
            data={
                "entity": TICKET_PRIORITY.hda_name,
                "columnExpressions": ID_DESCRIPTION_COLUMN_NAMES,
                "columenNames": ID_DESCRIPTION_COLUMN_NAMES,
            },
        )

    def list_ticket_sources(self, limit: int) -> dict:
        return self.http_request(
            url_suffix="WSC/Projection",
            method="POST",
            attempted_action="listing ticket priorities",
            data={
                "entity": _TICKET_SOURCE.hda_name,
                "columnExpressions": ID_DESCRIPTION_COLUMN_NAMES,
                "columenNames": ID_DESCRIPTION_COLUMN_NAMES,
                "start": 0,
                "limit": limit,
            },
        )

    def get_ticket_history(self, ticket_id: str) -> dict:
        return self.http_request(
            url_suffix=f"Ticket/History?ObjectID={ticket_id}",
            method="POST",
            attempted_action="getting ticket history",
        )

    def list_users(self, **kwargs):
        columns = [
            "ID",
            "User.FirstName",
            "User.LastName",
            "User.EMail",
            "User.Phone",
            "User.Mobile",
        ]

        params = {
            "entity": "Users",
            "columnExpressions": columns,
            "columnNames": columns,
            "start": (pagination := paginate(**kwargs)).start,
            "limit": pagination.limit,
        }

        if user_ids := argToList(kwargs["user_id"]):
            params["filter"] = parse_filter_conditions(
                tuple(f'{ID.hda_name} eq "{id_}"' for id_ in user_ids)
            )

        return self.http_request(
            url_suffix="WSC/Projection",
            method="POST",
            attempted_action="listing user(s)",
            params=params,
        )

    def list_groups(self, **kwargs):
        columns = [column.hda_name for column in (ID, DESCRIPTION, OBJECT_TYPE_ID)]

        params = {
            "entity": "UserGroup",
            "columnExpressions": columns,
            "columnNames": columns,
            "start": (pagination := paginate(**kwargs)).start,
            "limit": pagination.limit,
        }

        if group_id := kwargs.get("group_id"):
            params["filter"] = [
                parse_filter_conditions(f'{ID.hda_name} eq "{group_id}"')
            ]

        return self.http_request(
            url_suffix="WSC/Projection",
            method="POST",
            attempted_action="listing group(s)",
            params=params,
        )


class PaginateArgs(NamedTuple):
    start: int
    limit: int


def paginate(**kwargs) -> PaginateArgs:
    limit = kwargs["limit"]  # TODO required?

    page = kwargs.get("page")
    page_size = kwargs.get("page_size")

    none_arg_count = sum((page is None, page_size is None))

    if none_arg_count == 1:
        raise DemistoException(
            "To paginate, provide both `page` and `page_size` arguments."
            "To only get the first n results (without paginating), use the `limit` argument."
        )

    if none_arg_count == 2:  # neither page nor page_size provided
        return PaginateArgs(start=0, limit=limit)

    # here none_arg_count = 0, meaning both were provided
    page = safe_arg_to_number(page, "page")
    page_size = safe_arg_to_number(page_size, "page_size")

    return PaginateArgs(
        start=page * page_size,  # TODO 0 or 1 indexed?
        limit=min(limit, page_size),
    )


def create_ticket_command(client: Client, **kwargs) -> CommandResults:
    response = client.create_ticket(**kwargs)
    response = convert_response_dates(response)

    response_for_human_readable = response.copy()
    if not response_for_human_readable.get(SOLUTION.hda_name):
        # do not show empty or missing `Solution` value
        response_for_human_readable.pop(SOLUTION.hda_name, None)

    return CommandResults(
        outputs_prefix=f"{VENDOR}.Ticket",
        outputs_key_field=ID.hda_name,
        outputs=response,  # todo check human readable, titles
        readable_output=tableToMarkdown(
            "Ticket Created", t=response_for_human_readable
        ),
    )


def list_tickets_command(client: Client, args: dict) -> CommandResults:
    response = client.list_tickets(**args)
    response = convert_response_dates(response)

    return CommandResults(
        outputs=response["data"],
        outputs_prefix=f"{VENDOR}.Ticket",
        outputs_key_field=ID.hda_name,  # TODO choose fields for HR?
        raw_response=response,
    )


def add_ticket_attachment_command(client: Client, args: dict) -> CommandResults:
    entry_ids = args.pop("entry_id")
    response = client.add_ticket_attachment(entry_ids, **args)
    return CommandResults(
        readable_output=f"Added Attachment ID {response['attachmentId']} to ticket ID {args['ticket_id']}",
        raw_response=response,
    )


def list_ticket_attachments_command(client: Client, args: dict) -> CommandResults:
    response = client.list_ticket_attachments(**args)
    response = convert_response_dates(response)

    attachment_ids_str = ",".join(
        attachment[ID.hda_name] for attachment in response["data"]
    )
    return CommandResults(
        readable_output=f"Added attachment ID(s) {attachment_ids_str} to ticket {args['ticket_id']} succesfully",
        outputs=response["data"],
        outputs_prefix=f"{VENDOR}.Ticket.Attachment",
        outputs_key_field=ID.hda_name,
        raw_response=response,
    )


def list_ticket_statuses_command(client: Client, args: dict) -> CommandResults:
    response = client.list_ticket_statuses(**args)
    response = convert_response_dates(response)

    return CommandResults(
        outputs=response["data"],
        outputs_prefix=f"{VENDOR}.{TICKET_STATUS.hda_name}",
        raw_response=response,
    )


def add_ticket_comment_command(client: Client, args: dict) -> CommandResults:
    return CommandResults(
        readable_output=f"Comment was succesfully added to {args['ticket_id']}",
        raw_response=client.add_ticket_comment(**args),
    )


def change_ticket_status_command(client: Client, args: dict) -> CommandResults:
    response = client.change_ticket_status(**args)
    return CommandResults(
        readable_output=f"Changed status of ticket {args['ticket_id']} to {args['status']} successfully.",
        raw_response=response,
    )


def list_ticket_priorities_command(client: Client, _: dict) -> CommandResults:
    response = client.list_ticket_priorities()
    response = convert_response_dates(response)

    return CommandResults(
        outputs=response["data"],
        outputs_prefix=f"{VENDOR}.{_PRIORITY.hda_name}",
        readable_output=tableToMarkdown("HDA Ticket Priorities", response["data"]),
        raw_response=response,
    )


def list_ticket_sources_command(client: Client, args: dict) -> CommandResults:
    limit = safe_arg_to_number(args["limit"], "limit")

    response = client.list_ticket_sources(limit)
    response = convert_response_dates(response)

    outputs = map_id_to_description(response["data"])
    return CommandResults(
        outputs=outputs,
        outputs_prefix=f"{VENDOR}.{_TICKET_SOURCE.hda_name}",
        readable_output=tableToMarkdown(
            name="PAT HelpdeskAdvanced Ticket Sources",
            t=outputs,
            headers=["Source ID", "Source Description"],
        ),
        raw_response=response,
    )


def get_ticket_history_command(client: Client, args: dict) -> CommandResults:
    response = client.get_ticket_history(args["ticket_id"])
    response = convert_response_dates(response)
    return CommandResults(
        outputs=response["data"],
        outputs_prefix=f"{VENDOR}.Ticket",
        outputs_key_field=ID.hda_name,
        raw_response=response,
        readable_output=tableToMarkdown(
            name="PAT HelpdeskAdvanced Ticket History",
            t=response["data"],  # TODO check readable outputs
        ),
    )


def list_users_command(client: Client, args: dict) -> CommandResults:
    response = client.list_users(**args)
    response = convert_response_dates(response)

    return CommandResults(
        outputs=response["data"],
        outputs_prefix=f"{VENDOR}.User",
        outputs_key_field=ID.hda_name,
        raw_response=response,  # TODO HR fields
    )


commands: dict[str, Callable] = {
    "hda-create-ticket": create_ticket_command,
    "hda-list-tickets": list_tickets_command,
    "hda-add-ticket-comment": add_ticket_comment_command,
    "hda-change-ticket-status": change_ticket_status_command,
    "hda-add-ticket-attachment": add_ticket_attachment_command,
    "hda-list-ticket-attachments": list_ticket_attachments_command,
    "hda-list-ticket-priorities": list_ticket_priorities_command,
    "hda-list-ticket-sources": list_ticket_sources_command,
    "hda-get-ticket-history": get_ticket_history_command,
    "hda-list-users": list_users_command,
}


def main() -> None:
    demisto.debug(f"Command being called is {demisto.command()}")
    params = demisto.params()

    try:
        client = Client(
            base_url=urljoin(params["base_url"].removesuffix("HDAPortal"), "HDAPortal"),
            username=params["credentials"]["identifier"],
            password=params["credentials"]["password"],
            verify=not params["insecure"],
            proxy=params["proxy"],
        )

        if (command := demisto.command()) == "test-module":
            client.list_ticket_statuses(limit=1)
            result = "ok"

        elif command in commands:
            result = commands[command](client, demisto.args())

        else:
            raise NotImplementedError

        return_results(result)

    except Exception as e:
        return_error(
            "\n".join((f"Failed to execute {demisto.command()}.", f"Error: {e!s}"))
        )


""" ENTRY POINT """


if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
