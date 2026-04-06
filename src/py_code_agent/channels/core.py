import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import secrets
import time

logger = logging.getLogger(__name__)


class MessageCodec(ABC):
    @abstractmethod
    def encode(self, msg: "ChannelResponse") -> bytes: ...
    
    @abstractmethod
    def decode(self, data: bytes) -> Optional["ChannelMessage"]: ...


    @abstractmethod
    def encode_error(self, error: str) -> bytes: ...

    @abstractmethod
    def encode_auth_response(self, success: bool, token: Optional[str] = None, session_id: Optional[str] = None, error: Optional[str] = None) -> bytes: ...


    @abstractmethod
    def decode_raw(self, data: bytes) -> Optional[Dict[str, Any]]: ...


class JsonCodec(MessageCodec):
    def encode(self, msg: "ChannelResponse") -> bytes:
        payload = {
            "type": "message",
            "content": msg.content,
            "channel_id": msg.channel_id,
            "message_id": msg.message_id,
        }
        if msg.metadata:
            payload["metadata"] = msg.metadata
        return (json.dumps(payload) + "\n").encode()

    def decode(self, data: bytes) -> Optional["ChannelMessage"]:
        from py_code_agent.channels import ChannelMessage
        try:
            msg = json.loads(data.decode())
            if msg.get("type") == "message":
                return ChannelMessage(
                    content=msg.get("content", ""),
                    user_id=msg.get("user_id", "unknown"),
                    channel_id=msg.get("channel_id", ""),
                    message_id=msg.get("message_id"),
                    metadata=msg.get("metadata")
                )
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return None

    def encode_error(self, error: str) -> bytes:
        return (json.dumps({"type": "error", "message": error}) + "\n").encode()

    def encode_auth_response(self, success: bool, token: Optional[str] = None, session_id: Optional[str] = None, error: Optional[str] = None) -> bytes:
        payload = {"type": "auth_response", "success": success}
        if token:
            payload["token"] = token
        if session_id:
            payload["session_id"] = session_id
        if error:
            payload["error"] = error
        return (json.dumps(payload) + "\n").encode()

    def decode_raw(self, data: bytes) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


@dataclass
class UserSession:
    user_id: str
    session_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, UserSession] = {}

    def create_session(self, user_id: str, session_id: Optional[str] = None) -> UserSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        
        new_session = UserSession(
            user_id=user_id,
            session_id=session_id or self._generate_session_id()
        )
        self._sessions[new_session.session_id] = new_session
        return new_session

    def get_session(self, session_id: str) -> Optional[UserSession]:
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].messages.append({
                "role": role,
                "content": content,
                "timestamp": time.time()
            })

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        if session_id in self._sessions:
            return self._sessions[session_id].messages
        return []

    def clear_session(self, session_id: str) -> None:
        if session_id in self._sessions:
            del self._sessions[session_id]

    def list_sessions(self) -> List[UserSession]:
        return list(self._sessions.values())

    def _generate_session_id(self) -> str:
        return secrets.token_urlsafe(16)


class AuthManager:
    def __init__(self, api_keys: Optional[Set[str]] = None, require_auth: bool = True):
        self._api_keys = api_keys or set()
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self.require_auth = require_auth
        self._token_expiry = 3600

    def add_api_key(self, key: str) -> None:
        self._api_keys.add(key)

    def verify_api_key(self, key: str) -> bool:
        if not self.require_auth:
            return True
        return key in self._api_keys

    def generate_token(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = {
            "user_id": user_id,
            "created_at": time.time(),
            "expires_at": time.time() + self._token_expiry
        }
        logger.debug(f"Generated token for user: {user_id}")
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        if token in self._tokens:
            token_data = self._tokens[token]
            if time.time() < token_data["expires_at"]:
                return token_data
            else:
                logger.debug(f"Token expired for user: {token_data.get('user_id')}")
                del self._tokens[token]
        return None

    def revoke_token(self, token: str) -> None:
        if token in self._tokens:
            del self._tokens[token]

    def set_require_auth(self, require: bool) -> None:
        self.require_auth = require


from py_code_agent.channels import ChannelMessage, ChannelResponse, ChannelType

__all__ = ["MessageCodec", "JsonCodec", "SessionManager", "AuthManager", "UserSession", "ChannelMessage", "ChannelResponse", "ChannelType"]
