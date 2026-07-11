from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.container import ApplicationContainer
from app.core.errors import AuthenticationRequiredError


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container


ContainerDependency = Annotated[ApplicationContainer, Depends(get_container)]


def get_session(container: ContainerDependency) -> Iterator[Session]:
    with container.session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def require_authentication(request: Request, container: ContainerDependency) -> None:
    token = request.cookies.get(container.settings.session_cookie_name)
    if token is None or container.session_tokens.verify(token) is None:
        raise AuthenticationRequiredError()


Authenticated = Annotated[None, Depends(require_authentication)]

