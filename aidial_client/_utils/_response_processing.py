from typing import Type, cast

import httpx

from aidial_client._compatibility.pydantic import PYDANTIC_V2
from aidial_client._exception import ParsingDataError
from aidial_client._internal_types._generic import NoneType, ResponseT
from aidial_client._internal_types._model import (
    ExtraAllowModel,
    ExtraForbidModel,
)


def process_block_response(
    cast_to: Type[ResponseT], response: httpx.Response
) -> ResponseT:
    if cast_to == httpx.Response:
        return response
    elif cast_to == bytes:
        return response.content
    elif cast_to == str:
        return response.text
    elif cast_to == NoneType:
        return None
    elif cast_to == dict:
        try:
            return cast(ResponseT, response.json())
        except Exception as e:
            raise ParsingDataError(
                message=f"Error during parsing of response data: {str(e)}"
            )
    elif issubclass(cast_to, (ExtraForbidModel, ExtraAllowModel)):
        try:
            data = response.json()
            if PYDANTIC_V2:
                return cast_to.model_validate(data)
            else:
                return cast_to.parse_obj(data)  # type: ignore[attr-defined]
        except Exception as e:
            raise ParsingDataError(
                message=f"Error during parsing of response data: {str(e)}"
            )
    else:
        raise NotImplementedError("This cast_to type is not supported.")
