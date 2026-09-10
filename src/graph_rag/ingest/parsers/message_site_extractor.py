from typing import TYPE_CHECKING, Any

from .java_parser import _MEMBER_KINDS, _TYPE_KINDS, JavaParser

if TYPE_CHECKING:
    from tree_sitter import Node

_EVENT_LISTENER_ANNOS = {"EventListener", "TransactionalEventListener"}
_PUBLISH_METHODS = {"publishEvent"}
_BROKER_SEND_METHODS = {"send", "sendDefault", "convertAndSend", "convertSendAndReceive"}
# messaging-template simple type name → broker.
_TEMPLATE_BROKERS: dict[str, str] = {
    "KafkaTemplate": "kafka",
    "KafkaOperations": "kafka",
    "RabbitTemplate": "rabbit",
    "AmqpTemplate": "rabbit",
    "JmsTemplate": "jms",
    "JmsOperations": "jms",
    "SqsTemplate": "sqs",
    "QueueMessagingTemplate": "sqs",
}


class MessageSiteExtractor(JavaParser):
    """Raw event / messaging call sites the annotation model can't see —
    `@EventListener` methods, `publishEvent(...)` calls, and messaging-template
    `.send(...)` / `.convertAndSend(...)` calls with a literal destination.

    Subclasses `JavaParser` only to share its tree-sitter helper suite; it is
    never registered as a parser.
    """

    @classmethod
    def extract(
        cls,
        type_nodes: list["Node"],
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        package: str,
    ) -> list[dict[str, Any]]:
        """`@EventListener` methods (event type from `classes=` or the first
        parameter), `publishEvent(...)` sites (event type from the argument's
        `new X(...)` or a resolvable parameter), and `KafkaTemplate` /
        `RabbitTemplate` / `JmsTemplate` `.send(...)` / `.convertAndSend(...)`
        sites with a literal destination.
        """
        sites: list[dict[str, Any]] = []

        def walk(node: "Node", parent_qualified_name: str | None) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            type_simple = cls._text(name_node, content)
            type_qualified_name = cls._join(parent_qualified_name or package, type_simple)
            body = node.child_by_field_name("body")
            if body is None:
                return
            field_types = cls._field_types(body, content)
            for member in cls._body_members(body):
                if member.type in _MEMBER_KINDS:
                    cls._method_message_sites(
                        member,
                        content,
                        type_qualified_name,
                        type_simple,
                        field_types,
                        imported_types,
                        same_file_types,
                        sites,
                    )
                elif member.type in _TYPE_KINDS:
                    walk(member, type_qualified_name)

        for type_node in type_nodes:
            walk(type_node, None)
        return sites

    @classmethod
    def _method_message_sites(
        cls,
        member: "Node",
        content: bytes,
        type_qualified_name: str,
        type_simple_name: str,
        field_types: dict[str, str],
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        sites: list[dict[str, Any]],
    ) -> None:
        method_qualified_name = cls._member_qualified_name(
            member, content, type_qualified_name, type_simple_name
        )
        param_types: dict[str, str] = {}
        parameters = member.child_by_field_name("parameters")
        if parameters is not None:
            for parameter in parameters.children:
                if parameter.type not in ("formal_parameter", "spread_parameter"):
                    continue
                param_name = parameter.child_by_field_name("name")
                param_type = parameter.child_by_field_name("type")
                if param_name is not None and param_type is not None:
                    param_types[cls._text(param_name, content)] = cls._resolve_type_name(
                        cls._type_name_text(param_type, content),
                        imported_types,
                        same_file_types,
                    )

        for annotation_node in cls._annotation_nodes(member):
            name, _fqn, attributes, _line = cls._parse_annotation(
                annotation_node, content, imported_types, same_file_types
            )
            if name not in _EVENT_LISTENER_ANNOS:
                continue
            event_type = cls._listener_event_type(
                attributes, param_types, imported_types, same_file_types
            )
            if event_type:
                sites.append(
                    {
                        "kind": "event-listener",
                        "enclosing_qn": method_qualified_name,
                        "event_type": event_type,
                    }
                )

        body = member.child_by_field_name("body")
        if body is None:
            return
        for invocation in cls._descendants(body):
            if invocation.type != "method_invocation":
                continue
            name_node = invocation.child_by_field_name("name")
            if name_node is None:
                continue
            call = cls._text(name_node, content)
            arguments = invocation.child_by_field_name("arguments")
            if call in _PUBLISH_METHODS:
                sites.append(
                    {
                        "kind": "event-publish",
                        "enclosing_qn": method_qualified_name,
                        "event_type": cls._publish_arg_type(
                            arguments, content, param_types, imported_types, same_file_types
                        ),
                    }
                )
            elif call in _BROKER_SEND_METHODS:
                broker = cls._send_broker(invocation, content, field_types)
                destination = cls._first_string_argument(arguments, content)
                if broker and destination:
                    sites.append(
                        {
                            "kind": "broker-produce",
                            "enclosing_qn": method_qualified_name,
                            "broker": broker,
                            "destination": destination,
                        }
                    )

    @classmethod
    def _listener_event_type(
        cls,
        attributes: dict[str, Any],
        param_types: dict[str, str],
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> str | None:
        for key in ("classes", "value"):
            raw = attributes.get(key)
            if raw is None:
                continue
            items = raw if isinstance(raw, (list, tuple)) else [raw]
            for item in items:
                text = str(item).removesuffix(".class").strip()
                if text and text[0].isupper():
                    return cls._resolve_type_name(text, imported_types, same_file_types)
        return next(iter(param_types.values()), None)

    @classmethod
    def _publish_arg_type(
        cls,
        arguments: "Node | None",
        content: bytes,
        param_types: dict[str, str],
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> str | None:
        if arguments is None:
            return None
        argument = next((child for child in arguments.children if child.is_named), None)
        if argument is None:
            return None
        if argument.type == "object_creation_expression":
            type_node = argument.child_by_field_name("type")
            if type_node is not None:
                return cls._resolve_type_name(
                    cls._type_name_text(type_node, content), imported_types, same_file_types
                )
        if argument.type == "identifier":
            return param_types.get(cls._text(argument, content))
        return None

    @classmethod
    def _send_broker(
        cls, invocation: "Node", content: bytes, field_types: dict[str, str]
    ) -> str | None:
        receiver = invocation.child_by_field_name("object")
        if receiver is None:
            return None
        if receiver.type == "identifier":
            name = cls._text(receiver, content)
        elif receiver.type == "field_access":
            field_node = receiver.child_by_field_name("field")
            name = cls._text(field_node, content) if field_node is not None else ""
        else:
            return None
        declared = field_types.get(name)
        if declared:
            simple = declared.split("<", 1)[0].rsplit(".", 1)[-1].strip()
            if simple in _TEMPLATE_BROKERS:
                return _TEMPLATE_BROKERS[simple]
        lowered = name.lower()
        for token, broker in (
            ("kafka", "kafka"),
            ("rabbit", "rabbit"),
            ("amqp", "rabbit"),
            ("jms", "jms"),
            ("sqs", "sqs"),
        ):
            if token in lowered:
                return broker
        return None

    @classmethod
    def _first_string_argument(cls, arguments: "Node | None", content: bytes) -> str | None:
        if arguments is None:
            return None
        for child in arguments.children:
            if not child.is_named:
                continue
            if child.type == "string_literal":
                text = cls._text(child, content)
                return text[1:-1] if len(text) >= 2 else text
            return None
        return None

    @classmethod
    def _field_types(cls, body: "Node", content: bytes) -> dict[str, str]:
        types: dict[str, str] = {}
        for child in cls._body_members(body):
            if child.type != "field_declaration":
                continue
            type_node = child.child_by_field_name("type")
            field_type = (
                cls._collapse(cls._text(type_node, content)) if type_node is not None else "?"
            )
            for declarator in child.children:
                if declarator.type != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                if name_node is not None:
                    types[cls._text(name_node, content)] = field_type
        return types
