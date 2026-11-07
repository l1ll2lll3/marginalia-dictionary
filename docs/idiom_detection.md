# 불연속 숙어 탐지 설계 (2026-11-07)

문장 하나를 받아서 그 안에 든 숙어를 찾는 기능의 설계다. 숙어 단어 사이에 다른 말이 끼어 있어도 찾는다 (take **the cost** into account, look **it** up).

진행: 탐지기(`en-en/app/idiom_detect.py`)와 API(`POST /api/idioms/detect`)까지 구현했다. 운영 서버에는 아직 올리지 않았다.

---

## 1. 무엇을 하려는가

Marginalia에서 숙어가 필요한 곳은 두 군데다.

- **읽기 화면**: 독자가 단어를 누르면 그 단어가 걸친 숙어를 같이 보여준다. took를 눌렀는데 문장이 "She took the cost into account."면 *take into account*를 보여줘야 한다.
- **책 파이프라인**: 책 전체 문장에 숙어 주석을 미리 단다 (`book_package.json`).

둘 다 "숙어 이름 → 뜻"이 아니라 **"문장 → 그 안의 숙어"**가 필요하다. 지금 사전에는 이 기능이 없다. 탐지기를 사전 리포에 두고, reading은 이걸 가져다 쓴다.

---

## 2. 지금 있는 것

### 2.1 사전 API `/api/idiom` (`en-en/app/server.py`)

숙어 이름으로 찾는 기능이다. 불연속 형태를 넣으면 거의 다 못 찾는다.

| 입력 | 결과 |
|---|---|
| take into account / took into account | 찾음 |
| take the cost into account | 0건 |
| look it up, looked the word up | 0건 |
| made up his mind | 0건 (표제는 make up one's mind) |
| keep a close eye on | 0건 |

이유:
- 대체 검색이 "입력한 단어가 전부 숙어 안에 있는가"를 본다. 입력에 숙어 밖의 단어(the cost, it)가 섞이면 바로 탈락한다. 필요한 건 반대 방향이다.
- `LIKE '%up%'` 식 부분 일치라 cup, supper 같은 단어에도 걸린다.
- `idioms.meaning`에 **첫 뜻만** 저장한다 (`build_dict_db.py`). 그래서 look up의 뜻이 "Used other than figuratively or idiomatically: see look, up." 하나만 남는다.

### 2.2 reading 리포의 탐지기

| 날짜 | 파일 | 내용 |
|---|---|---|
| 2025-08 | `~/reading/wiktextract/*_idiom_detector.py` 12개 | 초기 실험. spaCy Matcher, `one's` 소유격 처리 시도 |
| 2026-03-05 | `~/reading/gutenberg/detect_gapped_idioms.py` | 처음 만든 불연속 탐지기 |
| 2026-04-03 | `~/everythingQnA/marginalia-pipeline/extract_disc_idioms.py` | v1. 구문 분석(dep)으로 오탐을 거르는 검증 추가 |
| **2026-04-11** | **`~/reading/gutenberg/extract_english_idioms_v2.py`** | **v2. v1의 검증 + 연속·불연속 매칭 + 여러 책 지원** |
| 2026-06-06 | `~/reading/gutenberg/extract_vocab_idioms.py` | v2를 import해서 씀 |

v2가 하는 일:
- `english_idioms.json`에서 2단어 구동사 4,144개를 뽑는다 (동사 + 손으로 고른 불변화사 18개).
- 3단어 고정 틀은 **코드에 손으로 적은 20개**를 쓴다 (take into account, bear in mind …).
- 패턴은 `[LEMMA:동사] [아무 토큰 0~2개] [불변화사]`다.
- 구문 분석으로 거른다. 불변화사가 `prep`이면 버리고, `prt`이면서 그 동사에 붙어 있으면 채택한다. 사이에 낀 말이 대명사나 동사의 목적어여도 채택한다.

v2를 `en_core_web_sm`으로 돌린 결과 (2026-11-07):

| 문장 | 결과 | 원인 |
|---|---|---|
| She took the cost into account. | ✅ | |
| They took the rumour for granted. | ✅ | |
| Bear these facts in mind. | ✅ | |
| I looked it up in the dictionary. | ✅ | |
| He gave it up. | ✅ | |
| He looked the word up. | ✅ + 오탐 *word up* | word up은 감탄사인데 품사를 보지 않음 |
| Turn the light off. | ✅ + 오탐 *light off* | 같은 이유 |
| He made up his mind at last. | ❌ *make up*(지어내다)으로 잡음 | `one's`가 든 숙어를 다루지 않음 |
| Keep a close eye on him. | ❌ | 4단어 이상 숙어를 다루지 않음, 수식어 close가 낌 |
| He picked the heavy book up. | ❌ + 오탐 *book up* | 사이가 3토큰이라 범위를 넘음 |
| She looked up the street. | ❌ 오탐 *look up* | sm 모델이 up을 전치사로 보지 못함 |

정리하면 v2의 한계는 다음과 같다.

1. 숙어 69,651개 중 약 4,164개만 쓴다.
2. 불변화사 18개와 고정 틀 20개를 손으로 골랐다. "근거 있는 목록으로만 만든다"는 규칙에 어긋난다.
3. 사이에 낄 수 있는 말을 토큰 수(0~2개)로만 제한한다. 그래서 긴 목적어는 놓치고, 상관없는 말이 낀 경우는 받아들인다.
4. 표제어의 품사를 보지 않는다 (word up, light off).

---

## 3. 근거 데이터: kaikki에 이미 다 있다

`english_idioms.json`(69,651개)은 reading의 `wiktextract/wiktionaryJsonl/extract_english_idioms.py`가 `true_idioms.json`을 걸러서 만들었다. 그런데 `true_idioms.json`을 어떤 기준으로 뽑았는지는 남아 있지 않다. 남아 있는 필드도 `word`, `pos`, `senses`(뜻풀이 문자열)뿐이다.

이미 있는 `kaikki-en.jsonl`을 직접 보면 탐지에 필요한 정보가 더 있다. 아래는 2026-11-07에 센 수치다.

| 항목 | 수 |
|---|---|
| 여러 단어 표제어 (전체) | 325,662 |
| 그중 `english_idioms.json`에 있는 것 | 71,919 |
| └ 활용형·이형 항목 (`form-of`, `alt-of`) | 44,838 |
| └ **원형 항목** | **27,081** |
| 　 뜻에 `idiomatic` 태그 | 9,224 |
| 　 뜻에 `transitive` 태그 | 3,079 |
| 구동사 범주 (`English phrasal verbs formed with "X"`) 원형 항목 | 5,045 (그중 verb 4,953, 타동 2,306) |
| └ 범주에 나오는 불변화사·전치사 종류 | 44가지 (up 1,138 · out 860 · off 461 · down 387 · on 340 · in 337 …) |
| 문자 그대로의 뜻("Used other than figuratively or idiomatically")이 있는 항목 | 2,708 |
| 숙어 원형 항목의 예문 | 50,107개 (16,701개 항목) |
| └ 표제어나 활용형이 그대로 들어 있는 예문 | 39,654 |
| └ **그대로 들어 있지 않은 예문** | **10,453** |

원형 항목의 자리표시어:

| 자리표시어 | 항목 수 | 예 |
|---|---|---|
| one's | 1,584 | make up one's mind, pull one's socks up |
| someone's | 479 | answer someone's prayers |
| someone | 320 | all over someone like a rash |
| oneself | 169 | |
| something | 80 | |
| somebody / somebody's / X / Y / somewhere | 12 | |

이 데이터에서 쓸 것:

- **구동사 범주**: 손으로 고른 불변화사 18개를 Wiktionary 범주로 바꾼다. 범주 이름에 불변화사가 들어 있다 (`formed with "up"`).
- **품사와 `transitive` 태그**: 타동사 숙어만 동사 뒤에 목적어가 낄 수 있다 (take *him* to task). 품사가 verb가 아니면 동사 패턴을 만들지 않는다. 그러면 word up, light off 오탐이 사라진다.
- **`forms`**: 활용형 목록이 붙어 있다 (took into account, taken into account).
- **예문**: 손으로 만들지 않은 평가 세트다 (§6). 그대로 들어 있지 않은 10,453개 안에 실제 불연속 용례가 들어 있다.
  - put up: "I think someone put **him** up to it."
  - put off: "I'll have to put **him** off."
  - gussy up: "gussie **them** up with a bit of cheese"
  - 잡음도 섞여 있다. "Near-synonyms: …" 줄, 비교급 같은 변형(drier than a dead dingo's donger), 110%처럼 숫자로 쓴 것이다.
- **문자 그대로의 뜻**: look up에는 "We stayed up late to look up at the stars." 같은 예문이 붙어 있다. 숙어처럼 보이지만 숙어 뜻이 아닌 경우를 가려내는 데 쓴다.

---

## 4. 설계

### 4.1 숙어 목록을 kaikki에서 다시 만든다

`english_idioms.json` 대신 `kaikki-en.jsonl`에서 기준을 정해 직접 뽑는다 (`build_idioms.py`, 2026-11-07 구현).

- 후보: 여러 단어 표제어 중 원형 항목. 활용형·이형 항목(`form_of`/`alt_of`만 있는 항목)은 원형에 붙인다. 연결이 이어지는 경우도 끝까지 따라간다 (pushed up the daisies → push up the daisies(이형) → push up daisies).
- 포함 조건 (하나라도 맞으면):
  1. 품사가 명사·고유명사가 아니다 (verb, adj, adv, prep, phrase, prep_phrase, proverb, intj …)
  2. 뜻에 `idiomatic` 태그가 있다
  3. 구동사 범주에 있다
  4. 명사라면 `figuratively` 태그가 있거나, 문자 그대로의 뜻이 따로 있다
- 뜻은 **전부** 태그와 함께 저장한다. 문자 그대로의 뜻에는 따로 표시한다.

**처음 기준은 너무 좁았다.** 처음에는 ② `idiomatic` 태그, ③ 구동사 범주, 품사 `phrase`·`prep_phrase`·`proverb`만 넣었다. 그러자 19,383개가 나왔고, 옛 목록 69,392개(정규형 기준) 중 8,466개가 기준 밖으로 빠졌다. 빠진 것 중에 eat one's words(`figuratively` 태그), hold dear(`transitive`만 있음), print money(`informal`만 있음)처럼 분명한 숙어가 많았다. Wiktionary에는 숙어 표시가 `idiomatic` 태그 하나로 통일돼 있지 않다.

그래서 ①을 넣었다. Wiktionary는 여러 단어 표제어를 뜻이 단어 뜻의 합이 아닐 때만 올린다(CFI). 따라서 여러 단어 동사·부사·전치사구는 태그가 없어도 숙어로 볼 수 있다. 실제로 기준 밖 여러 단어 동사 5,791개 중 5,361개가 옛 목록에 있었다. 명사는 11만 개가 대부분 복합명사(safety valve)라서 숙어 표시가 있을 때만 넣는다.

결과 (2026-11-07):

| 항목 | 수 |
|---|---|
| 숙어 (`idioms`) | 33,823 |
| 뜻 (`idiom_senses`) | 49,544 (문자 그대로 2,845) |
| 예문 (`idiom_examples`) | 61,092 |
| 활용형·이형 (`idiom_forms`) | 74,210 |
| 패턴 (`idiom_patterns`) | 38,453 |

옛 `english_idioms.json`과 비교 (`build_idioms.py --compare`):

| 옛 목록 69,392개의 행방 | 수 | 예 |
|---|---|---|
| 원형으로 들어감 | 24,000 | in a nutshell, see double |
| 활용형·이형으로 붙음 | 41,011 | took lying down, struck one's colors |
| 숙어 기준에서 빠짐 | 1,604 | king of the north, glory hole, snake in the grass |
| 원형이 기준에서 빠진 활용형 | 711 | tricks of the light, officers of the court |
| 원형이 kaikki에 없는 활용형 | 1,525 | binge watches, drip feed (원형이 하이픈·붙여 쓴 한 단어) |
| kaikki에 없음 | 653 | ass-backwards, self-contained (한 단어) |

옛 목록의 93.7%가 원형이나 활용형으로 들어왔다. 새로 들어온 원형은 8,871개다 (no man is an island, for sure, back to nature).

빠진 것 중에 **태그 없는 명사 숙어**(snake in the grass, trick of the light)가 있다. 또 make use of는 Wiktionary에 표제어가 없어서 들어오지 않는다. v2는 이걸 손으로 넣었었다. §8 참고.

### 4.2 숙어를 패턴으로 바꾼다

표제어를 토큰으로 나누고 토큰마다 종류를 정한다.

| 종류 | 무엇과 맞추나 | 예 |
|---|---|---|
| `HEAD` | 표제어 품사가 verb일 때 활용하는 단어. 활용형과 원형을 토큰별로 비교해 다른 자리로 정하고, 활용형이 없으면 첫 단어로 본다. 탐지 때는 품사 VERB/AUX인 토큰을 원형(lemma)이나 활용형으로 맞춘다 | take → took, taken |
| `LIT` | 고정 단어. 소문자로 정확히 맞춘다 | into, account |
| `POSS` | `one's`, `someone's`, `somebody's` → 소유격 대명사(my, his …)나 's 붙은 명사구 | make up **his** mind, **the boy's** |
| `NP` | `someone`, `somebody`, `something` → 명사구 하나 (머리 토큰의 하위 트리 전체) | all over **the poor man** like a rash |
| `REFL` | `oneself` → myself, himself, themselves … | |

여기에 **암묵적 목적어 자리**(`OBJ`)를 하나 더 둔다. 동사 숙어는 `HEAD`와 다음 `LIT` 사이에 목적어가 낄 수 있다. take [him] to task, take [the cost] into account, look [it] up이 그런 경우다.

처음 계획은 `transitive` 태그가 있는 숙어에만 이 자리를 두는 것이었다. 그런데 이 태그가 빠진 항목이 많다. take to task에도 `idiomatic`만 있다. 그래서 태그 대신 아래 규칙으로 정한다. 실제로 목적어인지는 탐지기가 구문 분석으로 확인한다(§4.3).

- 동사 다음 단어의 Wiktionary 품사(`words` 표)에 adv·prep·adj·particle이 있고, article·det·pron은 없을 때만 둔다. 그래서 up, into, dear, for 뒤에는 두고, an, the, it, use, care, place 뒤에는 두지 않는다. keep an eye on, make use of는 숙어 자신이 이미 목적어를 갖고 있기 때문이다.
- 숙어에 이미 자리표시어(`POSS`·`NP`·`REFL`)가 있으면 두지 않는다 (make up one's mind).
- 전치사로만 쓰이는 말(of, with, to …)로 끝나면 두지 않는다. 목적어가 맨 뒤에 오기 때문이다 (look up to him, get rid of it). 이 규칙 때문에 put [her success] down to luck처럼 목적어가 두 군데 오는 3단어 구동사는 놓친다.

결과 예:

```
take into account   → take [OBJ?] into account
look up             → look [OBJ?] up
hold dear           → hold [OBJ?] dear
make up one's mind  → make up [POSS] mind
keep an eye on      → keep an eye on
pull up one's socks → pull up [POSS] socks   (이형. 원형 pull one's socks up과 같은 숙어로 묶인다)
put up with         → put up with
```

### 4.3 맞추는 방법

v2는 끼는 말을 "토큰 0~2개"로 제한했다. 이걸 **"끼는 말이 문법적으로 설명되는가"**로 바꾼다.

1. **후보 찾기**: 숙어마다 가장 드문 `LIT` 단어를 열쇠로 색인한다 (account, mind, eye, task …). 문장 토큰으로 후보를 모은 뒤, `LIT` 단어가 문장에 다 있는 숙어만 남긴다.
2. **순서 맞추기**: `HEAD`부터 패턴 순서대로 문장 토큰에 맞춘다.
3. **끼는 말 검사**: 패턴 사이에 낀 토큰은 아래 중 하나여야 한다. 아니면 버린다.
   - 암묵적 목적어 자리: `HEAD`의 목적어(dobj, dative) **하위 트리 전체**. 길이 제한이 없으므로 the heavy book처럼 긴 목적어도 들어간다.
   - 자리표시어(`POSS`·`NP`·`REFL`)에 맞은 구간
   - 숙어 안 단어를 꾸미는 수식어: 머리가 패턴 안의 `LIT` 토큰이고 dep이 amod·advmod인 토큰 (keep a **close** eye on)
4. **구동사 검증** (v1·v2에서 가져옴): 불변화사가 `HEAD`에 prt나 advmod로 붙어 있어야 한다. 사이에 말이 끼었는데 불변화사가 prep이면 버린다.
5. **트리 경로** (`_catena`): 위에서 못 맞춘 동사 숙어는 구문 트리로 한 번 더 찾는다. 동사에서 시작해 부모-자식으로 **끊기지 않고** 고정 단어를 다 모을 수 있으면 맞다고 본다. 숙어 단어는 트리에서 이어져 있다(catena)는 성질을 쓴 것이다. give **you** pause, leave **his** home이 여기서 잡힌다. 자리표시어가 있는 숙어는 하지 않고(ring the bell ≠ ring someone's bell), conj·npadvmod·advcl·relcl 같은 관계로는 건너지 않는다.
6. **겹침 정리**: 같은 토큰을 쓰는 매칭이 여럿이면 고정 단어가 많은 쪽을 남긴다. 그래서 make up one's mind가 맞으면 make up은 버린다. 대명사는 세지 않는다 (gave it up은 give it up이 아니라 give up).

트리 경로를 넣기까지 측정한 값 (못 찾은 불연속 동사 숙어 708개 기준, 책은 달과 6펜스):

| 조건 | 더 잡는 예문 | 책에서 늘어나는 탐지 |
|---|---|---|
| 동사의 하위 트리에 고정 단어가 다 있다 | 649 | 4,676 (went up to the attic → go to) |
| 끊기지 않고 이어져 있다 (catena) | 572 | 1,883 (went back into → go into) |
| catena + §4.3 4번 검증 | 327 | 450 |

그 밖의 검증:
- 동사가 아닌 숙어에는 낀 말을 허용하지 않는다 (On one occasion ≠ on occasion). 자리표시어 자리만 받는다.
- be 숙어에 말이 끼면 버린다 (was a sensible man ≠ be a man).
- to부정사의 to는 전치사가 아니다 (want to go).
- 감탄사는 문장 앞에서만 받는다 (word up).
- a/an은 서로 받는다 (keep a close eye on).
- 복수 명사는 원형으로도 맞춘다 (red flags).

탐지에서 뺀 패턴 (`too_weak`): 동사가 아닌 기능어만의 말(out of, up to), be·have·do가 조동사처럼 쓰이는 말(there be, have in, do it), 고정 단어가 약한 자리표시어 패턴(piece of [NP], take [NP] to).

결과에는 `level`을 붙인다. 언어학 분류가 아니라 Wiktionary의 표시로 나눈 값이다.

| level | 기준 | 개수 | 예 |
|---|---|---|---|
| `idiom` | 뜻에 `idiomatic`이나 `figuratively` 태그 | 11,740 | kick the bucket, eat one's words, look up |
| `phrasal` | 태그는 없고 구동사 범주에 있음 | 3,895 | give up, look after |
| `phrase` | 둘 다 없음 | 18,219 | of course, in order to, hold dear, small room |

태그는 뜻 하나에 붙으므로 level은 "이 문장에서 숙어로 쓰였다"는 뜻이 아니라 "숙어 뜻이 있다"는 뜻이다.

### 4.4 손으로 정한 값

손으로 고른 목록은 없앤다. 다만 아래 몇 가지는 규칙으로 정해야 한다. 데이터가 아니라 문법 규칙이므로 코드 상수로 둔다.

- 자리표시어 단어 (one's, someone, something, oneself …): §3 표의 값 그대로
- 전치사로만 쓰이는 말 (`PREP_ONLY`: of, with, to, for, at, from, into …)
- 목적어 자리를 정하는 품사 묶음 (`OBJ_BEFORE_POS`, `NOMINAL_POS`)
- 끼는 말로 받아 주는 dep 종류: 목적어(`OBJ_DEPS`), amod, advmod
- 트리에서 건너지 않는 관계 (`NOT_IDIOM_LINK`)
- 재귀대명사 목록

---

## 5. 저장 구조

구현했다. 표 정의는 `docs/schema.md`의 idioms 절에 있다. 처음 설계에서 더한 것:

- `idioms.included_by`: 숙어로 넣은 이유. 기준을 고칠 때 무엇이 들고 나는지 보려고 둔다
- `idiom_examples`: 뜻별 예문. 평가 세트(§6)와 화면 표시에 쓴다
- `idiom_forms`: 활용형·이형 → 원형. `/api/idiom`이 활용형으로도 찾게 한다 (옛 목록은 활용형이 따로 행이었다)
- `idiom_patterns.source`: 이형은 어순이 달라서(pull up one's socks) 패턴을 따로 만든다

---

## 6. 평가

손으로 정답을 만들지 않는다. kaikki 예문이 정답이다. `idiom_examples` 표(61,092개, "Synonyms:"류 줄은 빌드 때 뺐다)를 쓴다. §3의 39,654 / 10,453은 옛 목록 기준으로 센 값이라 `eval_idioms.py`에서 새 목록으로 다시 센다.

| 세트 | 출처 | 재는 것 |
|---|---|---|
| 연속 | 고정 단어가 붙어 있는 예문, 활용형이 그대로 든 예문 (50,274) | 재현율. 연속 매칭이 깨지지 않았는가 |
| 자리표시어 | `one's`·`someone` 자리가 채워진 예문 (3,610) | 재현율 |
| 불연속 | 동사 숙어의 고정 단어 사이에 말이 낀 예문 (2,645) | 재현율. 이번 작업의 핵심 지표 |
| 문자 그대로 | 문자 그대로의 뜻에 붙은 예문 (1,491) | 숙어 뜻으로 잘못 잡는 비율 |
| 회귀 사례 | §2.2 표의 11문장 | 아래 기대값 |
| 실제 책 | 퍼블릭 도메인 책(달과 6펜스 등)에서 뽑은 탐지 결과 200개 | 정밀도. 사용자가 맞다/틀리다만 검토한다 |

- 예문 하나마다 "그 예문이 붙은 숙어를 찾았는가"를 본다.
- v2와 새 탐지기를 같은 세트로 돌려 비교한다.
- 세트는 예문을 숙어의 고정 단어와 맞춰서 나눈다. 문장 부호는 간격으로 세지 않고(warts-and-all), 고정 단어 사이가 6토큰을 넘으면 우연으로 본다. 동사가 아닌 숙어가 벌어진 경우는 우연이라 불연속으로 치지 않는다. 고정 단어가 다 없는 예문 3,054개는 제외한다 (drier than a dead dingo's donger, Fightin' fire with fire). 그래도 잡음이 조금 남으므로 재현율 숫자보다는, 못 찾은 예문을 묶어서 원인별로 세는 것을 기준으로 삼는다.

v2 기준선 (2026-11-07, `en_core_web_sm`, 예문 61,074개):

| 세트 | 예문 | 찾음 | 재현율 | v2가 아는 숙어의 예문 | 찾음 | 재현율 |
|---|---|---|---|---|---|---|
| 연속 | 50,274 | 7,364 | 14.6% | 9,173 | 7,353 | 80.2% |
| 자리표시어 | 3,610 | 0 | 0.0% | 0 | 0 | — |
| 불연속 | 2,645 | 1,262 | 47.7% | 1,562 | 1,262 | 80.8% |
| 문자 그대로 | 1,491 | 129 | 8.7% | 207 | 129 | 62.3% |

회귀 사례 5/11 통과. 예문당 다른 숙어 탐지 0.22개. 이 수는 재현율과 달리 오탐만 세는 값이 아니다 (맞는 것도 섞여 있다). 정밀도는 실제 책 세트로 따로 재야 한다.

새 탐지기 (2026-11-07, `en_core_web_sm`, 예문 61,176개. 숙어 표를 다시 빌드해서 예문 수가 조금 늘었다):

| 세트 | 예문 | 찾음 | 재현율 | v2 |
|---|---|---|---|---|
| 연속 | 50,364 | 43,616 | 86.6% | 14.6% |
| 자리표시어 | 3,610 | 3,033 | 84.0% | 0.0% |
| 불연속 | 2,645 | 2,121 | **80.2%** | 47.7% |
| 문자 그대로 | 1,493 | 1,272 | 85.2% | 8.7% |

회귀 사례 10/11 (v2는 5/11). 실패한 하나는 looked up the street이고, sm 모델이 up을 불변화사로 분석한다. 달과 6펜스 5,116문장에서 3,535개를 찾는다 (떨어진 것 432개).

정밀도는 아직 사람이 정식으로 재지 않았다. 구현하면서 샘플을 읽어 본 바로는 떨어진 탐지의 85% 안팎이 맞았다. 이건 구현자의 어림값이다. `eval_idioms.py --book`이 만드는 `idiom_review.tsv` 200개를 사용자가 판정하면 정식 수치가 된다.

읽는 법: v2의 약점은 **아는 숙어의 범위**다. 아는 숙어 안에서는 불연속 재현율이 80.8%로 높지만, 전체로 보면 47.7%다. 자리표시어 숙어는 하나도 모른다. 못 찾은 불연속 예문에는 3단어 이상 숙어가 많다 (rake him over the coals, nip it in the bud, put West Ham to the sword, keep close tabs on him). v2가 고정 틀을 20개만 알기 때문이다.

회귀 사례 기대값:

| 문장 | 기대 |
|---|---|
| She took the cost into account. | take into account |
| He looked the word up. | look up (word up 없음) |
| I looked it up in the dictionary. | look up |
| He made up his mind at last. | make up one's mind (make up 없음) |
| Keep a close eye on him. | keep an eye on |
| Turn the light off. | turn off (light off 없음) |
| He gave it up. | give up |
| They took the rumour for granted. | take for granted |
| Bear these facts in mind. | bear in mind |
| He picked the heavy book up from the floor. | pick up (book up 없음) |
| She looked up the street. | 없음 (모델 한계로 실패할 수 있다. §8) |

---

## 7. 파일과 API

| 파일 | 하는 일 |
|---|---|
| `en-en/scripts/build_idioms.py` | kaikki → `idioms`, `idiom_senses`, `idiom_patterns`. `build_dict_db.py`의 숙어 부분을 대신한다 |
| `en-en/app/idiom_detect.py` | 탐지기 라이브러리 + CLI (`--text "…"`). Docker가 app 폴더만 복사해서 scripts가 아니라 여기 둔다 |
| `en-en/scripts/eval_idioms.py` | §6 평가. v2와 비교 |

API (`en-en/app/server.py`):

```
POST /api/idioms/detect   {"text": "She took the cost into account."}
→ {"results": [{
     "idiom": "take into account",
     "as_found": "took the cost into account",
     "tokens": [[4, 8], [18, 22], [23, 30]],   // 숙어 단어의 글자 위치 (끼는 말 제외)
     "span": [4, 30],
     "gap": "the cost",
     "continuous": false,
     "level": "idiom",
     "senses": [{"gloss": "To consider or regard; …", "tags": ["idiomatic"], "literal": false}]
   }]}
```

`tokens`를 따로 주는 이유가 있다. 읽기 화면에서 took, into, account만 강조하고 the cost는 강조하지 않으려면 숙어 단어 각각의 위치가 필요하다.

요청에 `"levels": ["idiom", "phrasal"]`을 주면 그 level만 돌려준다. spaCy는 처음 요청 때 읽는다 (워커당 약 220MB, 첫 요청 약 1초, 그 뒤 문장당 수 ms). `/test` 페이지에 숙어 탐지 칸이 있다.

아직 안 한 것: `/api/idiom`이 뜻을 전부 돌려주게 하고, `LIKE '%단어%'` 부분 일치는 단어 경계 일치로 바꾼다.

---

## 8. 정하지 않은 것

1. **spaCy 모델**: `en_core_web_sm`으로 정했다 (2026-11-07). 큰 모델로 바꿔도 얻는 게 거의 없다.

   | 모델 | 크기 | 불연속 | 자리표시어 | 연속 | 회귀 |
   |---|---|---|---|---|---|
   | sm (전체) | 15MB | 80.2% | 84.0% | 86.6% | 10/11 |
   | lg (전체) | 435MB | 79.7% | 84.3% | 86.7% | 9/11 |
   | sm (3,000개 표본) | 15MB | 76.1% | 80.9% | 87.1% | 10/11 |
   | trf (3,000개 표본) | 484MB + torch | 79.1% | 84.8% | 88.3% | 10/11 |

   trf는 표본에서 조금 높지만 불연속 134개 중 4개 차이라서 의미 있는 차이라고 보기 어렵다. 메모리와 속도 부담에 비해 이득이 작다. looked up the street은 세 모델 다 틀린다. 모델을 바꿔서 풀리는 문제가 아니다.
2. **서버에서 돌릴지**: Fly VM이 shared-cpu-1x, 512MB다. 재 보니 탐지기를 읽은 워커 하나가 약 220MB라서 gunicorn 워커 2개면 약 440MB다. 빠듯하다. 워커를 1개로 줄이거나 VM을 1GB로 올리거나, 책은 미리 계산해 두고 서버는 사전 조회만 한다.
3. **뜻 고르기**: look up처럼 뜻이 여럿이면 처음에는 전부 보여준다. 문맥에 맞는 뜻 고르기는 reading의 `sense_select.py`와 묶어서 나중에 한다.
4. **관사·수의 변이**: keep **their eyes** on, take **a** hold of처럼 고정 단어 자체가 바뀌는 경우다. 1차에서는 다루지 않고, 평가에서 못 찾은 원인으로 얼마나 나오는지 보고 정한다.
5. **어순이 바뀌는 경우**: 수동태(the cost was taken into account)는 `HEAD`와 `LIT`가 붙어 있어서 그대로 잡힌다. 관계절(the strings he pulled)이나 도치는 1차 범위 밖이다.
6. **reading 쪽 교체**: `extract_english_idioms_v2.py`를 이 탐지기로 바꾸는 건 reading 세션에서 한다. `book_package.json`의 숙어 주석 형식은 reading에 맞춘다.
7. **태그 없는 명사 숙어**: snake in the grass, trick of the light, ghost in the machine은 명사이고 숙어 표시가 없어서 빠졌다(§4.1). 명사를 기능어(of, in, the …)가 든 것까지 넓히면 들어오지만 republic of the congo 같은 이름도 같이 들어온다. 평가 뒤에 정한다.
8. **화면에 무엇을 보여줄지**: small room, I think, open the door처럼 표시는 맞지만 문자 그대로 쓰인 탐지가 많다. `level`로 거를 수 있다. 기본값을 무엇으로 할지 정해야 한다.

---

## 9. 순서

1. ~~`build_idioms.py`: 목록 다시 만들기 + 지금 목록과의 차이 보고 (§4.1)~~ — 2026-11-07 완료
2. ~~`eval_idioms.py`: 평가 세트를 만들고 **v2부터** 잰다. 기준선이 된다~~ — 2026-11-07 완료 (§6)
3. ~~`idiom_detect.py`: §4.2~4.3 구현, 평가하면서 고치기~~ — 2026-11-07 완료
4. ~~모델 비교 (sm / lg / trf), 서버 메모리 측정~~ — 2026-11-07 완료 (§8)
5. ~~API 붙이기, `/test` 페이지에 숙어 탐지 칸 추가~~ — 2026-11-07 완료 (운영 배포는 안 함)
