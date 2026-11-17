"""Offline English-to-Korean worker. Stdin/stdout are private JSON pipes, never logs."""
import json
from pathlib import Path
import re
import sys

# Keep references/timecodes and only ambiguous technical nouns. Translate whole
# chunks in context; masking clauses or every 'shot' destroys Korean grammar.
GLOSSARY = {
    "jump cuts": "점프 컷", "jump cut": "점프 컷", "medium shot": "미디엄 샷",
    "close-up": "클로즈업", "wide shot": "와이드 샷", "focal length": "초점 거리",
    "zoom-out": "줌아웃", "zoom out": "줌아웃", "zoom-in": "줌인", "zoom in": "줌인",
    "zooms out": "줌아웃", "zooming out": "줌아웃", "zooms in": "줌인", "zooming in": "줌인",
    "static camera": "고정 카메라", "camera orbit": "카메라의 궤도 이동",
    "near side": "가까운 쪽", "near-side": "가까운 쪽",
    "far side": "먼 쪽", "far-side": "먼 쪽", "framing": "구도",
    "foreshortening": "원근에 따른 단축", "three-quarter view": "3/4 각도의 모습",
}
REFERENCE_TAG = r"<(?:Picture|Subject|Video|Audio)\s+\d+>"
REFERENCE_LIST = REFERENCE_TAG + r"(?:(?:,\s*(?:and\s+)?|\s+and\s+)" + REFERENCE_TAG + r")+"
PROTECTED = REFERENCE_LIST + "|" + REFERENCE_TAG + r"|\{\{[A-Za-z0-9_]+\}\}|(?<!\d)\d{2}:\d{2}\.\d{3}(?!\d)|\[Shot\s+\d+\]"
TERMS = "|".join(re.escape(k) for k in sorted(GLOSSARY, key=len, reverse=True))
TOKEN = re.compile("(" + PROTECTED + "|(?<![A-Za-z])(?:" + TERMS + ")(?![A-Za-z]))", re.I)


def _translate_chunk(text, model, tokenizer, target_tokenizer):
    if not re.search(r"[A-Za-z]", text):
        return text
    replacements = {}
    number = 0
    def protect(match):
        nonlocal number
        while "XREF" + str(number) in text:
            number += 1
        key = "XREF" + str(number); number += 1
        replacements[key] = GLOSSARY.get(match.group().lower(), match.group())
        return key
    protected = TOKEN.sub(protect, text)
    tokens = tokenizer.encode(protected, out_type=str)
    if len(tokens) > 768:
        raise ValueError("Source segment too long")
    outputs = model.translate_batch([tokens], beam_size=5, max_batch_size=1,
                                    max_input_length=0, max_decoding_length=1024)
    if len(outputs) != 1 or len(outputs[0].hypotheses[0]) >= 1024:
        raise ValueError("Incomplete translation")
    value = target_tokenizer.decode(outputs[0].hypotheses[0]).strip()
    if not value:
        raise ValueError("Empty translation")
    for key, original in replacements.items():
        pattern = re.compile(r"(?<![A-Za-z0-9])XREF\s*" + key[4:] + r"(?!\d)", re.I)
        if len(pattern.findall(value)) != 1:
            raise ValueError("Reference label not preserved")
        value = pattern.sub(lambda _: original, value)
    return re.match(r"\s*", text).group() + value + re.search(r"\s*$", text).group()


def translate_text(text, model, tokenizer, target_tokenizer=None, details=False):
    try:
        result = _translate_chunk(text, model, tokenizer, target_tokenizer or tokenizer)
        return (result, False) if details else result
    except ValueError:
        if not details:
            raise
        return text, True


def main():
    import ctranslate2
    import sentencepiece
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    home = Path(sys.argv[1])
    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(home / "src.spm.model"))
    target_tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(home / "tgt.spm.model"))
    model = ctranslate2.Translator(str(home), device="cpu", compute_type="int8",
                                 inter_threads=1, intra_threads=2)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        text = None
        try:
            request = json.loads(line)
            text = request["text"]
            if not isinstance(text, str) or not text or len(text) > 1200:
                raise ValueError("Invalid segment")
            value, partial = translate_text(text, model, tokenizer, target_tokenizer, details=True)
            answer = {"text": value}
            if partial:
                answer["warning"] = "번역 표기를 확인하지 못한 부분은 원문으로 표시합니다."
        except ValueError:
            answer = ({"text": text, "warning": "번역 표기를 확인하지 못한 구간은 원문으로 표시합니다."}
                      if isinstance(text, str) and 0 < len(text) <= 1200 else {"error": "번역 입력을 확인해 주세요."})
        except Exception:
            answer = {"error": "이 문장을 번역하지 못했습니다. 입력을 수정한 뒤 다시 시도해 주세요."}
        print(json.dumps(answer, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
