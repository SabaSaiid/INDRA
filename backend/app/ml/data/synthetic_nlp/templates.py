"""Split-isolated, class-specific synthetic NLP text templates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.ml.data.synthetic_nlp.scenarios import DatasetSplit, EventType, Language

TEMPLATE_VERSION: Final[str] = "synthetic-nlp-templates-v1"


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    template_id: str
    text: str


_LANGUAGE_CODES: Final[dict[Language, str]] = {
    "English": "en",
    "Hindi": "hi",
    "Hinglish": "hinglish",
}

# Every partition has independently authored surface forms. No template string or
# template identifier is shared across train, validation, and test.
_NORMAL_TEXT: Final[
    dict[DatasetSplit, dict[EventType, dict[Language, tuple[str, ...]]]]
] = {
    "train": {
        "URBAN_FLOOD": {
            "English": (
                "At {time}, {concept} was seen around {location}; {depth} remained after {rain}",
                "Blocked drains sent {depth} across lanes in {location} during {rain} at {time}",
            ),
            "Hindi": (
                "{time} {location} के आसपास {concept} देखा गया; {rain} के बाद {depth} जमा था",
                "{time} {location} में बंद नालियों से {depth} गलियों में फैल गया और {rain} जारी रही",
            ),
            "Hinglish": (
                "{time} {location} ke paas {concept} dikha; {rain} ke baad {depth} jama hai",
                "{location} mein blocked drains se {depth} galiyon par aa gaya during {rain}, update {time}",
            ),
        },
        "RIVER_BREACH": {
            "English": (
                "At {time}, {river} near {location}, sending {depth} into riverside homes",
                "A report from {location} says {concept}; fields took {depth} by {time}",
            ),
            "Hindi": (
                "{time} {location} के पास {river}; नदी किनारे के घरों में {depth} पहुंच गया",
                "{location} से सूचना है कि {concept}; {time} तक खेतों में {depth} भर गया",
            ),
            "Hinglish": (
                "{time} {location} ke paas {river}; riverside homes mein {depth} aa gaya",
                "{location} report mein {concept}; {time} tak fields mein {depth} bhar gaya hai",
            ),
        },
        "CLOUDBURST": {
            "English": (
                "A {duration}-minute {storm} caused {concept} over {location} at {time}",
                "At {time}, rain intensified almost instantly above {location}: {rain}, lasting {duration} minutes",
            ),
            "Hindi": (
                "{time} {location} में {duration} मिनट के {storm} से {concept} हुआ",
                "{location} के ऊपर {time} बारिश अचानक बहुत बढ़ी: {rain}, अवधि {duration} मिनट",
            ),
            "Hinglish": (
                "{time} {location} mein {duration}-minute {storm} se {concept} hua",
                "{location} ke upar rain suddenly intense hui at {time}: {rain}, {duration} minutes tak",
            ),
        },
        "CYCLONE_INUNDATION": {
            "English": (
                "At {time}, {cyclone} pushed a {tide} cm surge into {location}, producing {concept}",
                "{location} recorded {depth} as {wind} km/h winds and sea water arrived at {time}",
            ),
            "Hindi": (
                "{time} {cyclone} ने {tide} सेमी तूफानी ज्वार {location} में धकेला और {concept} हुआ",
                "{location} में {time} {wind} किमी प्रति घंटे की हवा के साथ समुद्री पानी आया और {depth} दर्ज हुआ",
            ),
            "Hinglish": (
                "{time} {cyclone} ne {tide} cm surge {location} mein push kiya, causing {concept}",
                "{location} mein {time} {wind} km/h hawa ke saath sea water aaya aur {depth} report hua",
            ),
        },
        "NOT_RELEVANT": {
            "English": (
                "At {time}, {location} issued {topic}; no flooding, breach, cloudburst, or cyclone impact was reported",
                "This is {concept} from {location} at {time}: {topic}, unrelated to an observed flood event",
            ),
            "Hindi": (
                "{time} {location} में {topic} जारी हुई; बाढ़, तटबंध टूटने, बादल फटने या चक्रवाती असर की सूचना नहीं है",
                "{location} से {time} यह {concept} है: {topic}, किसी देखी गई बाढ़ घटना से संबंधित नहीं",
            ),
            "Hinglish": (
                "{time} {location} ne {topic} diya; flood, breach, cloudburst ya cyclone impact report nahi hua",
                "Ye {location} ka {concept} hai at {time}: {topic}, observed flood event se related nahi",
            ),
        },
    },
    "validation": {
        "URBAN_FLOOD": {
            "English": (
                "By {time}, runoff had pooled to {depth} across the built-up blocks of {location} after {rain}",
                "Municipal drainage overflow left commuters wading through {depth} in {location} at {time}",
            ),
            "Hindi": (
                "{rain} के बाद {time} तक {location} के शहरी हिस्सों में {depth} बहकर जमा हो गया",
                "नगर निकासी उफनने से {time} {location} में यात्रियों को {depth} से होकर चलना पड़ा",
            ),
            "Hinglish": (
                "{rain} ke baad {time} tak {location} ke built-up blocks mein {depth} pool ho gaya",
                "municipal drain overflow se {location} mein commuters {depth} se guzre at {time}",
            ),
        },
        "RIVER_BREACH": {
            "English": (
                "Water escaped the river barrier beside {location} at {time}; {depth} reached adjacent farmland",
                "Residents reported {concept} downstream of {location}, where {river} by {time}",
            ),
            "Hindi": (
                "{time} {location} के पास नदी अवरोध से पानी बाहर निकला; पास के खेत में {depth} पहुंचा",
                "निवासियों ने {location} के नीचे की ओर {concept} बताया, जहां {time} {river}",
            ),
            "Hinglish": (
                "{time} {location} ke paas river barrier se paani nikla; nearby farm mein {depth} pahucha",
                "residents ne {location} downstream {concept} report kiya, jahan {time} {river}",
            ),
        },
        "CLOUDBURST": {
            "English": (
                "Rain gauges were overwhelmed during a {duration}-minute {concept} centred on {location} at {time}",
                "A sharply localized {storm} unloaded over {location} at {time}, unlike the wider {rain}",
            ),
            "Hindi": (
                "{time} {location} पर केंद्रित {duration} मिनट की {concept} के दौरान वर्षामापी की सीमा पार हो गई",
                "{time} {location} पर बहुत स्थानीय {storm} बरसा, जो व्यापक {rain} से अलग था",
            ),
            "Hinglish": (
                "{time} {location} par centred {duration}-minute {concept} mein rain gauges overload hue",
                "{location} par sharply local {storm} {time} unload hua, wider {rain} se alag",
            ),
        },
        "CYCLONE_INUNDATION": {
            "English": (
                "Sea water advanced into {location} under {cyclone} at {time}; the measured rise was {tide} cm",
                "The coastal edge of {location} saw {concept} with {wind} km/h onshore winds at {time}",
            ),
            "Hindi": (
                "{time} {cyclone} के दौरान समुद्री पानी {location} में आगे बढ़ा; बढ़ाव {tide} सेमी मापा गया",
                "{time} {location} के तटीय हिस्से में {wind} किमी प्रति घंटे की समुद्री हवा के साथ {concept} हुआ",
            ),
            "Hinglish": (
                "{time} {cyclone} ke under sea water {location} mein aage badha; rise {tide} cm measure hua",
                "{location} coast par {time} {wind} km/h onshore hawa ke saath {concept} hua",
            ),
        },
        "NOT_RELEVANT": {
            "English": (
                "The {time} message from {location} concerns {topic}; it contains no incident observation",
                "{location} shared {concept} at {time}, with ordinary conditions and no target event",
            ),
            "Hindi": (
                "{location} का {time} संदेश {topic} से संबंधित है; इसमें किसी घटना का प्रत्यक्ष अवलोकन नहीं है",
                "{location} ने {time} {concept} साझा की; स्थिति सामान्य है और कोई लक्षित घटना नहीं",
            ),
            "Hinglish": (
                "{location} ka {time} message {topic} ke baare mein hai; incident observation nahi hai",
                "{location} ne {time} {concept} share ki, normal conditions hain aur target event nahi",
            ),
        },
    },
    "test": {
        "URBAN_FLOOD": {
            "English": (
                "Surface runoff occupied the carriageway around {location}; observers estimated {depth} at {time}",
                "At {time}, water from overloaded city drains spread courtyard to courtyard in {location} during {rain}",
            ),
            "Hindi": (
                "{location} के आसपास सड़क पर सतही बहाव फैल गया; {time} पर्यवेक्षकों ने {depth} का अनुमान लगाया",
                "{rain} के दौरान {time} {location} में शहरी नालियों का पानी एक आंगन से दूसरे आंगन तक फैला",
            ),
            "Hinglish": (
                "{location} ke around surface runoff road par faila; observers ne {time} {depth} estimate kiya",
                "{rain} ke time overloaded city drains ka paani {location} mein courtyard to courtyard spread hua at {time}",
            ),
        },
        "RIVER_BREACH": {
            "English": (
                "A riverbank rupture upstream of {location} released a moving sheet of water at {time}, reaching {depth}",
                "At {time}, {river} outside {location}; the flow entered settlements beyond the channel",
            ),
            "Hindi": (
                "{location} के ऊपर की ओर नदी किनारा फटने से {time} बहता पानी निकला और {depth} तक पहुंचा",
                "{time} {location} के बाहर {river}; बहाव नदी मार्ग से बाहर बस्तियों में घुस गया",
            ),
            "Hinglish": (
                "{location} upstream riverbank rupture se {time} moving paani nikla aur {depth} tak pahucha",
                "{time} {location} ke bahar {river}; flow channel se nikal kar basti mein ghusa",
            ),
        },
        "CLOUDBURST": {
            "English": (
                "Within {duration} minutes, a sharply bounded deluge formed above {location} at {time}",
                "At {time}, {location} received {concept}: an abrupt rain wall from {storm}",
            ),
            "Hindi": (
                "{time} {duration} मिनट के भीतर {location} के ऊपर स्पष्ट सीमा वाली मूसलाधार बारिश बनी",
                "{time} {location} में {concept} हुई: {storm} से अचानक बारिश की दीवार आई",
            ),
            "Hinglish": (
                "{time} {duration} minutes ke andar {location} ke upar sharply bounded deluge bana",
                "{location} mein {time} {concept} hui: {storm} se abrupt wall of rain aayi",
            ),
        },
        "CYCLONE_INUNDATION": {
            "English": (
                "The surge front associated with {cyclone} crossed into {location} at {time}, lifting water by {tide} cm",
                "At {time}, post-landfall winds of {wind} km/h drove coastal water through {location}; {depth} was observed",
            ),
            "Hindi": (
                "{cyclone} से जुड़ा तूफानी ज्वार {time} {location} में घुसा और पानी {tide} सेमी बढ़ा",
                "{time} लैंडफॉल के बाद {wind} किमी प्रति घंटे की हवा ने {location} में समुद्री पानी धकेला; {depth} देखा गया",
            ),
            "Hinglish": (
                "{cyclone} ka surge front {time} {location} mein cross hua aur paani {tide} cm utha",
                "{time} post-landfall {wind} km/h hawa ne coastal paani {location} mein push kiya; {depth} observe hua",
            ),
        },
        "NOT_RELEVANT": {
            "English": (
                "At {time}, the only update from {location} was {topic}; there was no hazard report",
                "A routine message about {topic} circulated in {location} at {time}, without flood evidence",
            ),
            "Hindi": (
                "{time} {location} से केवल {topic} की सूचना थी; किसी खतरे की रिपोर्ट नहीं थी",
                "{location} में {time} {topic} का सामान्य संदेश चला; बाढ़ का कोई प्रमाण नहीं",
            ),
            "Hinglish": (
                "{time} {location} ka only update {topic} tha; hazard report nahi thi",
                "{location} mein {time} {topic} ka routine message circulate hua, flood evidence nahi",
            ),
        },
    },
}

_HARD_NEGATIVE_TEXT: Final[
    dict[DatasetSplit, dict[EventType, dict[Language, tuple[str, ...]]]]
] = {
    "train": {
        "URBAN_FLOOD": {
            "English": (
                "The river beside {location} remained within its banks; {depth} on roads came from blocked drains after {rain} at {time}",
            ),
            "Hindi": (
                "{location} के पास नदी किनारों के भीतर रही; {time} {rain} के बाद सड़क पर {depth} बंद नालियों से आया",
            ),
            "Hinglish": (
                "{location} ke paas nadi bank ke andar hai; road par {depth} blocked drains se aaya after {rain} at {time}",
            ),
        },
        "RIVER_BREACH": {
            "English": (
                "Although city streets near {location} are underwater, {time} checks show {river}; drainage is not the source",
            ),
            "Hindi": (
                "{location} की शहरी सड़कें पानी में हैं, लेकिन {time} जांच में {river}; कारण नाली नहीं है",
            ),
            "Hinglish": (
                "{location} city roads underwater hain, but {time} check mein {river}; drain iska source nahi hai",
            ),
        },
        "CLOUDBURST": {
            "English": (
                "Waterlogging followed, but the defining observation was a {duration}-minute {storm} over {location} at {time}",
            ),
            "Hindi": (
                "जलभराव बाद में हुआ, पर मुख्य अवलोकन {time} {location} पर {duration} मिनट का {storm} था",
            ),
            "Hinglish": (
                "waterlogging baad mein hua, main report {time} {location} ka {duration}-minute {storm} hai",
            ),
        },
        "CYCLONE_INUNDATION": {
            "English": (
                "Rain alone did not flood {location}; {cyclone} drove a {tide} cm sea surge inland at {time}",
            ),
            "Hindi": (
                "{location} में केवल बारिश से बाढ़ नहीं आई; {time} {cyclone} ने {tide} सेमी समुद्री ज्वार भीतर धकेला",
            ),
            "Hinglish": (
                "sirf rain se {location} flood nahi hua; {time} {cyclone} ne {tide} cm sea surge andar push kiya",
            ),
        },
        "NOT_RELEVANT": {
            "English": (
                "A forecast at {time} mentions {rain} near {location}, but no flooding or damage has been observed",
            ),
            "Hindi": (
                "{time} के पूर्वानुमान में {location} के पास {rain} का उल्लेख है, पर बाढ़ या नुकसान देखा नहीं गया",
            ),
            "Hinglish": (
                "{time} forecast mein {location} ke paas {rain} hai, but flood ya damage observe nahi hua",
            ),
        },
    },
    "validation": {
        "URBAN_FLOOD": {
            "English": (
                "Reports mention a nearby river, yet gauges are normal; {time} flooding in {location} is drain runoff measuring {depth}",
            ),
            "Hindi": (
                "पास की नदी का उल्लेख है, फिर भी जलमाप सामान्य है; {time} {location} का {depth} जलभराव नाली के बहाव से है",
            ),
            "Hinglish": (
                "nearby river mention hai but gauge normal; {time} {location} ka {depth} flood drain runoff se hai",
            ),
        },
        "RIVER_BREACH": {
            "English": (
                "The first call sounded like routine waterlogging, but inspection at {time} found {river} outside {location}",
            ),
            "Hindi": (
                "पहली कॉल सामान्य जलभराव जैसी थी, लेकिन {time} निरीक्षण में {location} के बाहर {river}",
            ),
            "Hinglish": (
                "first call routine waterlogging jaisi thi, but {time} inspection mein {location} ke bahar {river}",
            ),
        },
        "CLOUDBURST": {
            "English": (
                "Pooled water is present, yet the report class is determined by {concept} lasting {duration} minutes at {time} over {location}",
            ),
            "Hindi": (
                "पानी जमा है, फिर भी रिपोर्ट का आधार {location} पर {time} {duration} मिनट तक हुई {concept} है",
            ),
            "Hinglish": (
                "paani pool hua hai, but report ka basis {location} par {time} {duration}-minute {concept} hai",
            ),
        },
        "CYCLONE_INUNDATION": {
            "English": (
                "Urban drains are flowing, but {time} water in {location} arrived with {cyclone} and a {tide} cm surge",
            ),
            "Hindi": (
                "शहरी नालियां बह रही हैं, लेकिन {time} {location} में पानी {cyclone} और {tide} सेमी ज्वार के साथ आया",
            ),
            "Hinglish": (
                "urban drains chal rahe hain, but {time} {location} ka paani {cyclone} aur {tide} cm surge ke saath aaya",
            ),
        },
        "NOT_RELEVANT": {
            "English": (
                "The {time} bulletin for {location} discusses {cyclone} preparedness only; no inundation is reported",
            ),
            "Hindi": (
                "{location} की {time} बुलेटिन में केवल {cyclone} की तैयारी है; जलभराव की रिपोर्ट नहीं",
            ),
            "Hinglish": (
                "{location} ka {time} bulletin sirf {cyclone} preparedness discuss karta hai; inundation report nahi",
            ),
        },
    },
    "test": {
        "URBAN_FLOOD": {
            "English": (
                "Despite river-related rumours, the barrier is intact; {time} water in {location} is {depth} from overloaded sewers",
            ),
            "Hindi": (
                "नदी संबंधी अफवाहों के बावजूद अवरोध सुरक्षित है; {time} {location} में {depth} पानी उफनते सीवर से है",
            ),
            "Hinglish": (
                "river rumours ke despite barrier intact hai; {time} {location} mein {depth} paani overloaded sewer se hai",
            ),
        },
        "RIVER_BREACH": {
            "English": (
                "Drain crews found no blockage: the moving {depth} flow at {location} began when {river} at {time}",
            ),
            "Hindi": (
                "नाली दल को रुकावट नहीं मिली: {location} में बहता {depth} पानी तब शुरू हुआ जब {time} {river}",
            ),
            "Hinglish": (
                "drain crew ko blockage nahi mila: {location} ka moving {depth} flow tab start hua jab {time} {river}",
            ),
        },
        "CLOUDBURST": {
            "English": (
                "The flooded lane is secondary evidence; {time} instruments over {location} captured a {duration}-minute {concept}",
            ),
            "Hindi": (
                "पानी भरी गली द्वितीय प्रमाण है; {time} {location} के उपकरणों ने {duration} मिनट की {concept} दर्ज की",
            ),
            "Hinglish": (
                "flooded lane secondary evidence hai; {time} {location} instruments ne {duration}-minute {concept} capture ki",
            ),
        },
        "CYCLONE_INUNDATION": {
            "English": (
                "The same road floods in monsoon, but this {time} event followed {cyclone}: sea rise reached {tide} cm in {location}",
            ),
            "Hindi": (
                "यह सड़क मानसून में भी भरती है, लेकिन {time} की घटना {cyclone} के बाद हुई: {location} में समुद्री बढ़ाव {tide} सेमी था",
            ),
            "Hinglish": (
                "ye road monsoon mein bhi flood hoti hai, but {time} event {cyclone} ke baad hua: {location} sea rise {tide} cm",
            ),
        },
        "NOT_RELEVANT": {
            "English": (
                "A social post from {location} at {time} repeats the word flood as a metaphor; it reports {topic}, not an incident",
            ),
            "Hindi": (
                "{location} की {time} सोशल पोस्ट में बाढ़ शब्द रूपक है; संदेश {topic} का है, घटना का नहीं",
            ),
            "Hinglish": (
                "{location} ki {time} social post mein flood metaphor hai; message {topic} ka hai, incident ka nahi",
            ),
        },
    },
}


def _materialize(
    raw: dict[DatasetSplit, dict[EventType, dict[Language, tuple[str, ...]]]],
    kind: str,
) -> dict[DatasetSplit, dict[EventType, dict[Language, tuple[TemplateSpec, ...]]]]:
    return {
        split: {
            event_type: {
                language: tuple(
                    TemplateSpec(
                        template_id=(
                            f"{split}-{event_type.casefold().replace('_', '-')}-"
                            f"{_LANGUAGE_CODES[language]}-{kind}-{index:02d}"
                        ),
                        text=text,
                    )
                    for index, text in enumerate(texts, start=1)
                )
                for language, texts in languages.items()
            }
            for event_type, languages in classes.items()
        }
        for split, classes in raw.items()
    }


NORMAL_TEMPLATES: Final = _materialize(_NORMAL_TEXT, "normal")
HARD_NEGATIVE_TEMPLATES: Final = _materialize(_HARD_NEGATIVE_TEXT, "hard")


def templates_for(
    split: DatasetSplit,
    event_type: EventType,
    language: Language,
    *,
    hard_negative: bool,
) -> tuple[TemplateSpec, ...]:
    source = HARD_NEGATIVE_TEMPLATES if hard_negative else NORMAL_TEMPLATES
    return source[split][event_type][language]


__all__ = [
    "HARD_NEGATIVE_TEMPLATES",
    "NORMAL_TEMPLATES",
    "TEMPLATE_VERSION",
    "TemplateSpec",
    "templates_for",
]
