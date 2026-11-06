"""The three roles in the words people see, with what each can do. The keys are what the server
stores (`member`, `reviewer`, `admin`)."""

ROLE_LABELS = {"member": "Contributor", "reviewer": "Coordinator", "admin": "Administrator"}
ROLE_CHOICES = {label: key for key, label in ROLE_LABELS.items()}
ROLE_DESCRIPTIONS = {
    "member": "Adds recordings and asks questions.",
    "reviewer": "Also looks after their own groups and what each group allows.",
    "admin": "Full control: reviews and publishes, manages settings and people.",
}


def role_label(role: str) -> str:
    """The role as a person reads it. Unknown ones are shown as stored."""
    return ROLE_LABELS.get(role, role)
