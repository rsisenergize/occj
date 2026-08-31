from pydantic import BaseModel


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    display_name: str


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    display_name: str

    model_config = {"from_attributes": True}
