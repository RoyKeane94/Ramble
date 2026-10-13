from django.db.models import Q

TEXT_FIELDS = (
    "tidied_text",
    "raw_transcript",
    "original_transcript",
    "boosted_transcript",
    "gpt_transcript",
    "gpt_transcribe_transcript",
    "whisper_1_transcript",
    "gpt_transcribe_tidied_text",
    "whisper_1_tidied_text",
    "gpt_tidied_text",
    "edited_text",
)


def text_search_q(query):
    q = Q()
    for field in TEXT_FIELDS:
        q |= Q(**{f"{field}__icontains": query})
    return q
