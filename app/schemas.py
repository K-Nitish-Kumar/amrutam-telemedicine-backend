import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# EmailStr requires email-validator; avoid extra runtime dependencies by using strict-ish string validation.

class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Registration(APIModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=2, max_length=150)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[1] or " " in value:
            raise ValueError("Enter a valid email")
        return value


class Login(APIModel):
    email: str
    password: str


class MFAChallenge(APIModel):
    challenge_token: str
    code: str = Field(pattern=r"^[0-9]{6}$")


class MFACode(APIModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


class UserResponse(APIModel):
    id: uuid.UUID
    email: str
    role: str
    mfa_enabled: bool


class ProfileUpdate(APIModel):
    full_name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=32, pattern=r"^[+0-9() .-]*$")


class DoctorCreate(APIModel):
    user_email: str
    license_no: str = Field(min_length=4, max_length=100)
    specialty: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    bio: str = Field(default="", max_length=1000)
    fee_minor: int = Field(ge=0, le=10_000_000)
    verified: bool = False


class DoctorResponse(APIModel):
    id: uuid.UUID
    display_name: str
    specialty: str
    city: str
    bio: str
    fee_minor: int
    verified: bool


class SlotCreate(APIModel):
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def check_timezone_and_duration(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Both timestamps must contain a timezone offset")
        if not (self.start_at < self.end_at):
            raise ValueError("end_at must be after start_at")
        if (self.end_at - self.start_at).total_seconds() > 7200:
            raise ValueError("Slot duration cannot exceed 120 minutes")
        return self


class SlotResponse(APIModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    status: str


class BookingCreate(APIModel):
    slot_id: uuid.UUID


class ConsultationResponse(APIModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    slot_id: uuid.UUID
    status: str
    fee_minor: int
    created_at: datetime


class StatusUpdate(APIModel):
    status: Literal["in_progress", "completed", "cancelled"]


class Medication(APIModel):
    name: str = Field(min_length=2, max_length=120)
    dosage: str = Field(min_length=1, max_length=150)
    frequency: str = Field(min_length=1, max_length=150)
    duration_days: int = Field(ge=1, le=365)


class PrescriptionCreate(APIModel):
    medications: list[Medication] = Field(min_length=1, max_length=20)
    instructions: str = Field(default="", max_length=2000)


class PrescriptionResponse(APIModel):
    id: uuid.UUID
    consultation_id: uuid.UUID
    issued_by: uuid.UUID
    created_at: datetime
    document: PrescriptionCreate


class PaymentResponse(APIModel):
    id: uuid.UUID
    consultation_id: uuid.UUID
    amount_minor: int
    currency: str
    status: str


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(APIModel):
    message: str
