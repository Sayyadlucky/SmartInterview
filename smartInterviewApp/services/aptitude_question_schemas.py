QUESTION_TYPE_SINGLE_CHOICE = 'single_choice'
QUESTION_TYPE_MULTIPLE_CHOICE = 'multiple_choice'
QUESTION_TYPE_TRUE_FALSE = 'true_false'
QUESTION_TYPE_NUMERIC = 'numeric'
QUESTION_TYPE_TEXT_INPUT = 'text_input'
QUESTION_TYPE_FILL_BLANK = 'fill_blank'
QUESTION_TYPE_IMAGE_CHOICE = 'image_choice'
QUESTION_TYPE_MATCHING = 'matching'
QUESTION_TYPE_ORDERING = 'ordering'

OTHER_OPTION_KEY = 'OTHER'


def make_text_option(key, label, *, requires_input=False, input_type='text', placeholder=''):
    return {
        'key': key,
        'label': label,
        'requires_input': requires_input,
        'input_type': input_type,
        'placeholder': placeholder,
    }


def make_image_option(key, image_url, *, label='', alt=''):
    return {
        'key': key,
        'label': label,
        'media': {
            'type': 'image',
            'url': image_url,
            'alt': alt,
        },
    }


def make_question_image(image_url, *, alt='', position='below_question'):
    return {
        'type': 'image',
        'url': image_url,
        'alt': alt,
        'position': position,
    }


def single_choice_answer(correct_key, *, accepted_other_values=None, case_sensitive=False):
    return {
        'type': QUESTION_TYPE_SINGLE_CHOICE,
        'correct_key': correct_key,
        'accepted_other_values': list(accepted_other_values or []),
        'case_sensitive': case_sensitive,
    }


def multiple_choice_answer(correct_keys):
    return {
        'type': QUESTION_TYPE_MULTIPLE_CHOICE,
        'correct_keys': list(correct_keys or []),
    }


def numeric_answer(value, *, tolerance=0):
    return {
        'type': QUESTION_TYPE_NUMERIC,
        'value': value,
        'tolerance': tolerance,
    }


def text_answer(accepted_values, *, case_sensitive=False, trim_spaces=True):
    return {
        'type': QUESTION_TYPE_TEXT_INPUT,
        'accepted_values': list(accepted_values or []),
        'case_sensitive': case_sensitive,
        'trim_spaces': trim_spaces,
    }


def true_false_answer(value):
    return {
        'type': QUESTION_TYPE_TRUE_FALSE,
        'value': bool(value),
    }


def matching_answer(pairs):
    return {
        'type': QUESTION_TYPE_MATCHING,
        'pairs': dict(pairs or {}),
    }


def ordering_answer(correct_order):
    return {
        'type': QUESTION_TYPE_ORDERING,
        'correct_order': list(correct_order or []),
    }


def default_scoring_schema(*, partial_credit=False, normalize_text=True):
    return {
        'partial_credit': partial_credit,
        'normalize_text': normalize_text,
    }


def validate_question_payload(question_type, options, answer_schema):
    errors = []
    option_list = options or []
    schema = answer_schema or {}
    option_keys = {
        option.get('key')
        for option in option_list
        if isinstance(option, dict) and option.get('key')
    }

    for index, option in enumerate(option_list):
        if not isinstance(option, dict):
            errors.append(f'Option {index + 1} must be an object.')
            continue
        if option.get('requires_input') and not option.get('input_type'):
            errors.append(f'Option {option.get("key") or index + 1} requires input_type.')

    if question_type in {QUESTION_TYPE_SINGLE_CHOICE, QUESTION_TYPE_IMAGE_CHOICE}:
        correct_keys = schema.get('correct_keys')
        if correct_keys:
            if not isinstance(correct_keys, list) or len(correct_keys) != 1:
                errors.append(f'{question_type} must define exactly one correct key.')
                correct_key = None
            else:
                correct_key = correct_keys[0]
        else:
            correct_key = schema.get('correct_key')
        if not correct_key:
            errors.append(f'{question_type} must define exactly one correct_key.')
        elif correct_key != OTHER_OPTION_KEY and correct_key not in option_keys:
            errors.append(f'Correct key {correct_key} is not present in options.')

    if question_type == QUESTION_TYPE_MULTIPLE_CHOICE:
        correct_keys = schema.get('correct_keys')
        if not isinstance(correct_keys, list) or not correct_keys:
            errors.append('multiple_choice must define at least one correct key.')
        else:
            for correct_key in correct_keys:
                if correct_key != OTHER_OPTION_KEY and correct_key not in option_keys:
                    errors.append(f'Correct key {correct_key} is not present in options.')

    if question_type == QUESTION_TYPE_NUMERIC and 'value' not in schema:
        errors.append('numeric must define value.')

    if question_type in {QUESTION_TYPE_TEXT_INPUT, QUESTION_TYPE_FILL_BLANK}:
        accepted_values = schema.get('accepted_values')
        if not isinstance(accepted_values, list) or not accepted_values:
            errors.append(f'{question_type} must define a non-empty accepted_values list.')

    if question_type == QUESTION_TYPE_MATCHING:
        pairs = schema.get('pairs')
        if not isinstance(pairs, dict) or not pairs:
            errors.append('matching must define a non-empty pairs object.')

    if question_type == QUESTION_TYPE_ORDERING:
        correct_order = schema.get('correct_order')
        if not isinstance(correct_order, list) or not correct_order:
            errors.append('ordering must define a non-empty correct_order list.')
        else:
            for correct_key in correct_order:
                if correct_key not in option_keys:
                    errors.append(f'Ordering key {correct_key} is not present in options.')

    if question_type == QUESTION_TYPE_IMAGE_CHOICE:
        if not option_list:
            errors.append('image_choice must define image options.')
        for option in option_list:
            if not isinstance(option, dict):
                continue
            media = option.get('media')
            if not isinstance(media, dict) or media.get('type') != 'image' or not media.get('url'):
                errors.append(f'Image option {option.get("key") or "unknown"} must include image media.')

    return errors
