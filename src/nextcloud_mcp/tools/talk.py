"""Nextcloud Talk tools — conversations, messages, and participants via OCS API."""

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..permissions import PermissionLevel, require_permission
from ..state import get_client

# Conversation type IDs used by Nextcloud Talk
_CONVERSATION_TYPES: dict[int, str] = {
    1: "one-to-one",
    2: "group",
    3: "public",
    4: "changelog",
    5: "former-one-to-one",
    6: "note-to-self",
}

# Room types accepted when creating conversations
_VALID_ROOM_TYPES = {2: "group", 3: "public"}

# Participant type IDs used by Nextcloud Talk
_PARTICIPANT_TYPES: dict[int, str] = {
    1: "owner",
    2: "moderator",
    3: "user",
    4: "guest",
    5: "user-following-public-link",
    6: "guest-moderator",
}


def _format_conversation(room: dict[str, Any]) -> dict[str, Any]:
    """Extract the most useful fields from a raw room object."""
    return {
        "token": room["token"],
        "type": _CONVERSATION_TYPES.get(room.get("type", 0), f"unknown({room.get('type')})"),
        "name": room.get("displayName", room.get("name", "")),
        "description": room.get("description", ""),
        "read_only": room.get("readOnly", 0) == 1,
        "has_call": room.get("hasCall", False),
        "unread_messages": room.get("unreadMessages", 0),
        "unread_mention": room.get("unreadMention", False),
        "last_activity": room.get("lastActivity", 0),
        "is_favorite": room.get("isFavorite", False),
        "participant_count": room.get("participantCount", 0),
        "can_leave": room.get("canLeaveConversation", False),
        "can_delete": room.get("canDeleteConversation", False),
    }


def _format_message_compact(msg: dict[str, Any]) -> str:
    """Format a message as a compact single line: [id] author: text."""
    msg_id = msg.get("id", 0)
    author = msg.get("actorDisplayName", "unknown")
    text = msg.get("message", "")
    return f"[{msg_id}] {author}: {text}"


def _format_message_full(msg: dict[str, Any]) -> dict[str, Any]:
    """Extract the most useful fields from a raw message object."""
    return {
        "id": msg["id"],
        "actor_type": msg.get("actorType", ""),
        "actor_id": msg.get("actorId", ""),
        "actor_display_name": msg.get("actorDisplayName", ""),
        "timestamp": msg.get("timestamp", 0),
        "message": msg.get("message", ""),
        "message_type": msg.get("messageType", ""),
        "system_message": msg.get("systemMessage", ""),
        "is_replyable": msg.get("isReplyable", False),
    }


def _format_participant(p: dict[str, Any]) -> dict[str, Any]:
    """Extract the most useful fields from a raw participant object."""
    return {
        "attendee_id": p.get("attendeeId", 0),
        "actor_type": p.get("actorType", ""),
        "actor_id": p.get("actorId", ""),
        "display_name": p.get("displayName", ""),
        "participant_type": _PARTICIPANT_TYPES.get(p.get("participantType", 0), f"unknown({p.get('participantType')})"),
        "in_call": p.get("inCall", 0) > 0,
    }


def _register_read_tools(mcp: FastMCP) -> None:
    """Register read-only Talk tools."""

    @mcp.tool()
    @require_permission(PermissionLevel.READ)
    async def list_conversations(include_notifications_disabled: bool = False) -> str:
        """List all Talk conversations the current user is part of.

        Returns conversations sorted by last activity (newest first).
        Each conversation includes: token (unique ID for API calls), type,
        name, unread counts, and permissions.

        Args:
            include_notifications_disabled: If true, also return conversations where
                notifications are disabled (default: false).

        Returns:
            JSON list of conversation objects.
        """
        client = get_client()
        params: dict[str, str] = {}
        if not include_notifications_disabled:
            params["noStatusUpdate"] = "0"
        data = await client.ocs_get("apps/spreed/api/v4/room", params=params)
        conversations = [_format_conversation(room) for room in data]
        return json.dumps(conversations, indent=2, default=str)

    @mcp.tool()
    @require_permission(PermissionLevel.READ)
    async def get_conversation(token: str) -> str:
        """Get details about a specific Talk conversation.

        Args:
            token: The conversation token (short alphanumeric ID, e.g. "abc12xyz").
                   Use list_conversations to find tokens.

        Returns:
            JSON object with conversation details.
        """
        client = get_client()
        data = await client.ocs_get(f"apps/spreed/api/v4/room/{token}")
        return json.dumps(_format_conversation(data), indent=2, default=str)

    @mcp.tool()
    @require_permission(PermissionLevel.READ)
    async def get_messages(
        token: str,
        limit: int = 50,
        before_message_id: int = 0,
        include_system: bool = False,
    ) -> str:
        """Get chat messages from a Talk conversation.

        Returns messages in reverse chronological order (newest first).
        Uses a compact format: "[id] author: message text" — one line per message.

        IMPORTANT: Start with a small limit (20-50). If you need more context,
        use before_message_id with the oldest message ID from the previous call
        to paginate backwards through the history.

        Args:
            token: The conversation token. Use list_conversations to find tokens.
            limit: Maximum number of messages to return (1-200, default: 50).
                   Start small to avoid exceeding response size limits.
            before_message_id: Fetch messages older than this message ID (for pagination).
                               Use the smallest message ID from a previous call.
                               Default 0 means start from the newest message.
            include_system: Include system messages like "User joined",
                            "Conversation created" (default: false — only chat messages).

        Returns:
            Compact text with one message per line: "[id] author: message".
            The last line shows pagination info if more messages may exist.
        """
        client = get_client()
        limit = max(1, min(200, limit))
        params: dict[str, str] = {
            "lookIntoFuture": "0",
            "limit": str(limit),
            "setReadMarker": "0",
        }
        if before_message_id:
            params["lastKnownMessageId"] = str(before_message_id)
        data = await client.ocs_get(f"apps/spreed/api/v1/chat/{token}", params=params)

        if not include_system:
            data = [m for m in data if not m.get("systemMessage")]

        lines = [_format_message_compact(msg) for msg in data]

        if data:
            oldest_id = min(m["id"] for m in data)
            lines.append(f"\n--- {len(data)} messages. For older messages, call with before_message_id={oldest_id} ---")

        return "\n".join(lines)

    @mcp.tool()
    @require_permission(PermissionLevel.READ)
    async def get_participants(token: str) -> str:
        """List participants in a Talk conversation.

        Args:
            token: The conversation token. Use list_conversations to find tokens.

        Returns:
            JSON list of participant objects, each with: attendee_id,
            actor_id, display_name, participant_type (owner/moderator/user/guest),
            in_call status.
        """
        client = get_client()
        data = await client.ocs_get(f"apps/spreed/api/v4/room/{token}/participants")
        participants = [_format_participant(p) for p in data]
        return json.dumps(participants, indent=2, default=str)


def _register_write_tools(mcp: FastMCP) -> None:
    """Register write and destructive Talk tools."""

    @mcp.tool()
    @require_permission(PermissionLevel.WRITE)
    async def send_message(token: str, message: str, reply_to: int = 0) -> str:
        """Send a chat message to a Talk conversation.

        Supports Markdown formatting. Messages can be up to 32000 characters.
        Use @mention syntax to mention users: @"user-id" or @"display name".

        Args:
            token: The conversation token. Use list_conversations to find tokens.
            message: The message text to send (supports Markdown).
            reply_to: Optional message ID to reply to (default: 0 = not a reply).

        Returns:
            JSON object of the sent message with its assigned ID.
        """
        client = get_client()
        post_data: dict[str, Any] = {"message": message}
        if reply_to:
            post_data["replyTo"] = reply_to
        data = await client.ocs_post(f"apps/spreed/api/v1/chat/{token}", data=post_data)
        return json.dumps(_format_message_full(data), indent=2, default=str)

    @mcp.tool()
    @require_permission(PermissionLevel.WRITE)
    async def create_conversation(
        room_type: int,
        name: str,
        invite: str = "",
    ) -> str:
        """Create a new Talk conversation.

        Args:
            room_type: 2 for group conversation, 3 for public conversation.
                       Group conversations are invite-only.
                       Public conversations can be joined via link.
            name: Display name for the conversation.
            invite: Optional user ID to invite (for group conversations).

        Returns:
            JSON object with the created conversation details, including its token.
        """
        if room_type not in _VALID_ROOM_TYPES:
            valid = ", ".join(f"{k} ({v})" for k, v in _VALID_ROOM_TYPES.items())
            raise ValueError(f"Invalid room_type {room_type}. Valid types: {valid}")
        client = get_client()
        post_data: dict[str, Any] = {"roomType": room_type, "roomName": name}
        if invite:
            post_data["invite"] = invite
        data = await client.ocs_post("apps/spreed/api/v4/room", data=post_data)
        return json.dumps(_format_conversation(data), indent=2, default=str)

    @mcp.tool()
    @require_permission(PermissionLevel.DESTRUCTIVE)
    async def delete_message(token: str, message_id: int) -> str:
        """Delete a chat message from a Talk conversation.

        Only the message author or a moderator can delete a message.
        The message is replaced with "Message deleted" in the conversation.

        Args:
            token: The conversation token.
            message_id: The ID of the message to delete.

        Returns:
            Confirmation message.
        """
        client = get_client()
        await client.ocs_delete(f"apps/spreed/api/v1/chat/{token}/{message_id}")
        return f"Message {message_id} deleted from conversation {token}."

    @mcp.tool()
    @require_permission(PermissionLevel.DESTRUCTIVE)
    async def leave_conversation(token: str) -> str:
        """Leave a Talk conversation.

        After leaving, the user will no longer receive notifications or see
        the conversation in their list. For group conversations, the user
        can be re-invited. For one-to-one conversations, this removes the
        conversation permanently for the user.

        Args:
            token: The conversation token of the conversation to leave.

        Returns:
            Confirmation message.
        """
        client = get_client()
        await client.ocs_delete(f"apps/spreed/api/v4/room/{token}/participants/self")
        return f"Left conversation {token}."


def register(mcp: FastMCP) -> None:
    """Register Talk tools with the MCP server."""
    _register_read_tools(mcp)
    _register_write_tools(mcp)
