import re
from datetime import date, datetime
from enum import Enum
from typing import Optional, List, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class DetailSearchUserProfile(BaseModel):
    id: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None


class SearchUserProfileResponse(BaseModel):
    results: List[DetailSearchUserProfile]


class IndustryCategory(str, Enum):
    CAPITAL_GOODS = "Capital Goods"
    COMMERCIAL = "Commercial & Professional Services"
    CONSUMER_GOODS = "Consumer Goods"
    CONSUMER_SERVICES = "Consumser Services"
    EDUCATION = "Education"
    ENERGY = "Energy"
    FINANCE = "Financial Service"
    GOVERNMENT = "Government"
    HEALTHCARE = "Healthcare"
    INSURANCE = "Insurance"
    MEDIA = "Media & Entertainment"
    REAL_ESTATE = "Real Estate"
    HARDWARE = "Semiconductor & Hardware Components"
    TECHNOLOGY = "Software & Technolgy Services"
    TELECOMMUNICATION = "Telecommunication Services"
    TRANSPORTATION = "Transportation"
    UTILITIES = "Utilities"
    OTHERS = "Others"


class JobCategory(str, Enum):
    TECH_SPECIALIST = "Tech - Specialist"
    TECH_MANAGING = "Tech - Managing"
    NON_TECH = "Non Tech"
    TEACHER_LECTURER = "Teacher/Lecturer"
    STUDENT = "Student"
    ENTERPRENEUR = "Enterpreneur"
    OTHER = "Other"


class ParticipantType(str, Enum):
    NON_PARTICIPANT = "Non Participant"
    IN_PERSON = "In Person Participant"
    ONLINE = "Online Participant"
    KEYNOTE_SPEAKER = "Keynote Speaker"
    SPEAKER = "Speaker"
    ORGANIZER = "Organizer"
    VOLUNTEER = "Volunteer"
    SPONSOR = "Sponsor"
    COMMUNITY = "Community"
    PATRON = "Patron"


class TShirtSize(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"
    XXXL = "XXXL"
    XXXXL = "4XL"


class Gender(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Prefer Not To Say"


class LookingForOption(str, Enum):
    OPEN_OPPORTUNITIES = "Open Opportunities"
    CLOSE_OPPORTUNITIES = "Close Opportunities"
    NETWORKING = "Networking"
    HIRING = "Hiring"


class CountryReference(BaseModel):
    id: int
    name: str


class StateReference(BaseModel):
    id: int
    name: str


class CityReference(BaseModel):
    id: int
    name: str


class UserProfileBase(BaseModel):
    # Satu validator untuk semua field tags
    @field_validator("interest", "expertise", mode="before", check_fields=False)
    def split_tags(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [tag.strip() for tag in v.split(",") if tag.strip()]
        if isinstance(v, list):
            return v
        raise ValueError("Tags must be a comma-separated string or a list of strings.")


class UserProfileUpdateBase(UserProfileBase):
    @field_validator("phone", mode="before", check_fields=False)
    def validate_phone_number(cls, v: Any) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^\+[1-9]\d{1,14}$", str(v)):
            raise ValueError(
                "Phone number must be in international format, e.g., +6281234567890."
            )
        return str(v)

    # Satu validator untuk semua username

    @field_validator(
        "github_username",
        "facebook_username",
        "linkedin_username",
        "twitter_username",
        "instagram_username",
        mode="before",
        check_fields=False,
    )
    def validate_username(cls, v: Any) -> Optional[str]:
        if v is None:
            return v
        if "://" in str(v) or "/" in str(v):
            raise ValueError("Please provide only the username, not the full URL.")
        return str(v)

    # Satu validator untuk semua checkbox agreement
    @field_validator(
        "coc_acknowledged", "terms_agreed", "privacy_agreed", check_fields=False
    )
    def must_be_true(cls, v: Any) -> bool:
        if v is not True:
            raise ValueError("This field must be checked to proceed.")
        return v


# 2. Model CREATE mewarisi dari BASE


class UserProfilePublic(UserProfileBase):
    """Model untuk data publik yang bisa dilihat semua orang."""

    model_config = ConfigDict(from_attributes=True)

    profile_picture: str | None
    first_name: str | None
    last_name: str | None
    job_category: JobCategory | None
    job_title: str | None
    country: Optional[CountryReference] = None
    bio: str | None
    participant_type: str | None
    share_my_email_and_phone_number: Optional[bool] = False
    share_my_job_and_company: Optional[bool] = False
    share_my_location: Optional[bool] = False
    share_my_interest: Optional[bool] = False
    share_my_public_social_media: Optional[bool] = False
    share_my_data_to_sponsor: Optional[bool] = False
    retain_my_data_for_next_pycon: Optional[bool] = False
    coc_acknowledged: Optional[bool] = False
    terms_agreed: Optional[bool] = False
    privacy_agreed: Optional[bool] = False

    @model_validator(mode="before")
    @classmethod
    def extract_relationships(cls, data: Any) -> Any:
        if hasattr(data, "__dict__"):
            result = {k: v for k, v in data.__dict__.items() if not k.startswith("_")}

            if hasattr(data, "country") and data.country:
                result["country"] = {"id": data.country.id, "name": data.country.name}

            return result
        return data


class UserProfilePrivate(UserProfilePublic):
    """Model untuk data privat yang hanya bisa dilihat oleh user itu sendiri."""

    """Berisi semua field umum yang diisi oleh user dari form."""
    model_config = ConfigDict(from_attributes=True)

    email: EmailStr | None

    # Professional Info
    industry_categories: IndustryCategory | None
    company: str | None
    experience: int | None

    # Personal Details
    t_shirt_size: TShirtSize | None
    gender: Gender | None
    date_of_birth: date | None
    phone: str | None

    # Location
    state: Optional[StateReference] = None
    city: Optional[CityReference] = None
    zip_code: Optional[str] = None
    address: str | None

    # Interests and Expertise
    interest: List[str] | None
    looking_for: LookingForOption | None
    expertise: List[str] | None

    # Social & Portfolio
    website: HttpUrl | None
    github_username: str | None
    facebook_username: str | None
    linkedin_username: str | None
    twitter_username: str | None
    instagram_username: str | None

    # Attendance
    attendance_day_1: Optional[bool] = None
    attendance_day_1_at: Optional[datetime] = None
    attendance_day_2: Optional[bool] = None
    attendance_day_2_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def extract_relationships(cls, data: Any) -> Any:
        if hasattr(data, "__dict__"):
            result = {k: v for k, v in data.__dict__.items() if not k.startswith("_")}

            # Add nested objects
            if hasattr(data, "country") and data.country:
                result["country"] = {"id": data.country.id, "name": data.country.name}
            if hasattr(data, "state") and data.state:
                result["state"] = {"id": data.state.id, "name": data.state.name}
            if hasattr(data, "city") and data.city:
                result["city"] = {"id": data.city.id, "name": data.city.name}

            return result
        return data


class UserProfileCreate(UserProfileUpdateBase):
    """Berisi semua field umum yang diisi oleh user dari form."""

    first_name: str = Field(
        ..., min_length=1, max_length=50, description="User's first name."
    )
    last_name: str = Field(
        ..., min_length=1, max_length=50, description="User's last name."
    )
    # email: Optional[EmailStr] = Field(None, description="User's email address.")
    share_my_email_and_phone_number: Optional[bool] = Field(
        None, description="Allow sharing email and phone number."
    )
    bio: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Short biography about the user.",
    )

    # Professional Info
    industry_categories: Optional[IndustryCategory] = None
    company: Optional[str] = Field(
        None, max_length=100, description="Company or organization name."
    )
    job_category: JobCategory = Field(..., description="Category of the user's job.")
    job_title: str = Field(..., max_length=100, description="User's job title.")
    share_my_job_and_company: Optional[bool] = Field(
        None, description="Allow sharing job and company information."
    )
    experience: Optional[int] = Field(
        None, ge=0, description="Years of professional experience."
    )

    # Personal Details
    t_shirt_size: Optional[TShirtSize] = None
    gender: Optional[Gender] = None
    date_of_birth: Optional[date] = None
    phone: Optional[str] = Field(
        None, description="Phone number including country code (e.g., +6281234567890)."
    )
    participant_type: Optional[str] = Field(
        "Non Participant", description="Type of participant."
    )
    # Location
    # Di-handle dengan API menggunakan ID dari dropdown
    country_id: int = Field(..., description="User's country ID.")
    state_id: Optional[int] = Field(None, description="User's state/province ID.")
    city_id: Optional[int] = Field(None, description="User's city ID.")
    zip_code: Optional[str] = Field(
        None, max_length=10, description="Postal or zip code."
    )
    address: Optional[str] = Field(None, max_length=255, description="Full address.")
    share_my_location: Optional[bool] = Field(
        None, description="Allow sharing location information."
    )

    # Interests and Expertise
    interest: Optional[List[str]] = Field(None, description="List of user's interests.")
    share_my_interest: Optional[bool] = Field(
        None, description="Allow sharing interests."
    )
    looking_for: Optional[LookingForOption] = None
    expertise: Optional[List[str]] = Field(
        None, description="List of skills user is offering or searching for."
    )

    # Social & Portfolio
    website: Optional[HttpUrl] = None
    github_username: Optional[str] = None
    facebook_username: Optional[str] = None
    linkedin_username: Optional[str] = None
    twitter_username: Optional[str] = None
    instagram_username: Optional[str] = None
    share_my_public_social_media: Optional[bool] = Field(
        None, description="Allow sharing social media profiles."
    )
    share_my_data_to_sponsor: Optional[bool] = Field(
        None, description="Opt-in to share data with sponsors."
    )
    retain_my_data_for_next_pycon: Optional[bool] = Field(
        None, description="Opt-in to retain data for the next PyCon ID."
    )

    # Agreements
    coc_acknowledged: bool = Field(..., description="Code of Conduct acknowledgement.")
    terms_agreed: bool = Field(..., description="Terms and Conditions agreement.")
    privacy_agreed: bool = Field(..., description="Privacy Policy agreement.")


class UserProfileDB(UserProfileCreate):
    """
    Model yang merepresentasikan data lengkap di database.
    Mewarisi semua dari Base dan menambahkan field 'profile_picture'.
    """

    # Profile Info
    profile_picture: Optional[str] = Field(
        None, description="URL to the profile picture."
    )


class UserProfileEditSuccessResponse(UserProfileDB):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "first_name": "string",
                "last_name": "string",
                "email": "user@example.com",
                "bio": "menyemmmmmmmmmmmmmmmmmm",
                "industry_categories": "Technology",
                "company": "string",
                "job_category": "Tech - Specialist",
                "job_title": "string",
                "experience": 4,
                "t_shirt_size": "S",
                "gender": "Male",
                "date_of_birth": "2025-09-29",
                "phone": "+61",
                "participant_type": "Non Participant",
                "country_id": 102,
                "state_id": 1836,
                "city_id": 38932,
                "zip_code": "string",
                "address": "string",
                "interest": ["string", "masokk pa eko"],
                "looking_for": "Open Opportunities",
                "expertise": ["memasak", "meminum", "luar biasa"],
                "website": "https://example.com/",
                "github_username": "string",
                "facebook_username": "string",
                "linkedin_username": "",
                "twitter_username": "string",
                "instagram_username": "string",
                "share_my_data_to_sponsor": True,
                "retain_my_data_for_next_pycon": True,
                "coc_acknowledged": True,
                "terms_agreed": True,
                "privacy_agreed": True,
                "profile_picture": "https://example.com/files/roti.jpeg",
            }
        },
    )


# --- Contoh Penggunaan ---
if __name__ == "__main__":
    # 1. Contoh data valid
    valid_data = {
        "profile_picture": "https://example.com/profile.jpg",
        "first_name": "Citra",
        "last_name": "Wijaya",
        "email": "citra.w@email.com",
        "bio": "A creative designer focused on user experience and interface design.",
        "job_category": "Tech - Specialist",
        "job_title": "UI/UX Designer",
        "country": "Indonesia",
        "interest": "figma, design thinking, user research",  # Akan diubah jadi list
        "coc_acknowledged": True,
        "terms_agreed": True,
        "privacy_agreed": True,
    }

    try:
        profile = UserProfileDB(**valid_data)
        print("✅ Data valid!")
        print(profile.model_dump_json(indent=2))
        # Cek hasil konversi tags
        print(f"\nInterests as list: {profile.interest}")
    except Exception as e:
        print("❌ Gagal validasi data valid:")
        print(e)

    print("\n" + "-" * 50 + "\n")

    # 2. Contoh data tidak valid
    invalid_data = {
        "profile_picture": "not-a-url",  # URL tidak valid
        "first_name": "Andi",
        "last_name": "Pratama",
        "email": "andi@.com",  # Email tidak valid
        "bio": "Too short",  # Bio terlalu pendek (min_length=10)
        "job_category": "Tech - Managing",
        "job_title": "Developer Manager",
        "country": "Indonesia",
        "phone": "081234567890",  # Format telepon salah
        "github_username": "https://github.com/andipratama",  # Seharusnya username saja
        "coc_acknowledged": False,  # Harus True
        "terms_agreed": True,
        "privacy_agreed": True,
    }

    try:
        profile = UserProfileDB(**invalid_data)
    except Exception as e:
        print("❌ Gagal validasi data tidak valid (sesuai harapan):")
        print(e)


class EnumDropdownItem(BaseModel):
    value: str
    label: str


class IndustryCategoryDropdownResponse(BaseModel):
    results: List[EnumDropdownItem]


class JobCategoryDropdownResponse(BaseModel):
    results: List[EnumDropdownItem]


class ParticipantTypeDropdownResponse(BaseModel):
    results: List[EnumDropdownItem]
