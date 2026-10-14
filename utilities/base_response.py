from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, create_model


class BaseResponseModel(BaseModel):
    code: str = "200"
    message: str = "success"
    data: Any = ""

    model_config = ConfigDict(coerce_numbers_to_str=True)

def response_wrapper(wrapped_class: BaseModel):
    if not hasattr(wrapped_class, "__annotations__"):
        return BaseResponseModel

    # define a unique model name for fastapi/utils/get_model_definitions
    model_name_unique: str = wrapped_class.__module__ + wrapped_class.__name__ + uuid4().hex[:6]

    base_annotations: dict = BaseResponseModel.__annotations__
    attr = {"data": (wrapped_class, ...)}
    wrapper_model = create_model(model_name_unique, __base__=BaseResponseModel, **attr)

    def __init__(self, *args, **kwargs):
        # If there are keys in the args not present in the base model, need to put them inside data
        if kwargs.keys() != base_annotations.keys():
            data = {}

            # Find any args specific to the wrapped class and put them inside data
            wrapped_keys = kwargs.keys() - BaseResponseModel.__annotations__.keys()

            for i in wrapped_keys:
                data[i] = kwargs.pop(i)

            kwargs.update({"data": data})

        super(wrapper_model, self).__init__(**kwargs)

    wrapper_model.__init__ = __init__
    return wrapper_model
