# 계절 배너 이미지

Google Gemini로 생성한 이미지를 배너 비율(5:1, 2000×400)로 잘라 쓴 것입니다.
원본 오른쪽 아래의 Gemini 워터마크는 잘라낸 범위 밖에 있어 배너에 보이지 않습니다.

| 파일 | 계절 | 달 | 그림 | 출처 |
|---|---|---|---|---|
| `season-winter.webp` | 겨울 | 12·1·2월 | 눈 내리는 밤, 불 켜진 통나무집 | Gemini 생성 |
| `season-spring.webp` | 봄 | 3·4·5월 | 벚꽃·개나리 핀 강변 | Gemini 생성 |
| `season-summer.webp` | 여름 | 6·7·8월 | 야자수 해변과 바다 | Gemini 생성 |
| `season-autumn.webp` | 가을 | 9·10·11월 | 단풍 든 계곡 | Gemini 생성 |

배너 높이에 맞춰 `background-size: cover`로 씁니다. 사진이 화려해서 글자 쪽(왼쪽)을 어둡게 덮습니다.

## 붙이는 방법 (예시)

```css
.season-banner { position: relative; border-radius: 24px; overflow: hidden; padding: 28px 32px; color: #fff;
  background: var(--season-img) center / cover no-repeat, #5d6f86; }
.season-banner::before { content: ""; position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(10,16,28,.55), rgba(10,16,28,.25) 45%, rgba(10,16,28,0) 75%); }
.season-banner > * { position: relative; }
```

```js
// 달력에 보이는 달(0~11)로 계절을 고른다: 12~2 겨울, 3~5 봄, 6~8 여름, 9~11 가을
const SEASONS = {
  winter: { img: '/img/seasons/season-winter.webp', label: '겨울의 일정', title: '한 해의 목표를 따뜻하게 마무리해요', sub: '남은 일정은 가볍게 나누고, 새해의 기회를 준비해 보세요.', icon: '❄️' },
  spring: { img: '/img/seasons/season-spring.webp', label: '봄의 일정', title: '새로운 시작을 차근차근 준비해요', sub: '작은 준비를 쌓아가는 봄, 이번 달 지원 일정을 확인해 보세요.', icon: '🌸' },
  summer: { img: '/img/seasons/season-summer.webp', label: '여름의 일정', title: '집중이 필요한 순간을 놓치지 마세요', sub: '중요한 마감과 시험 일정을 한눈에 보고, 오늘 할 일을 정리해요.', icon: '☀️' },
  autumn: { img: '/img/seasons/season-autumn.webp', label: '가을의 일정', title: '준비한 만큼 결실을 거두는 계절이에요', sub: '마감이 몰리는 시기, 우선순위를 정해 하나씩 끝내 보세요.', icon: '🍁' },
};
const seasonOf = m => [11, 0, 1].includes(m) ? 'winter' : m <= 4 ? 'spring' : m <= 7 ? 'summer' : 'autumn';
function applySeason(el, month) {
  const s = SEASONS[seasonOf(month)];
  el.style.setProperty('--season-img', `url("${s.img}")`);
  // 제목·문구·아이콘 갱신은 화면 마크업에 맞게
}
```

이미지 경로는 FastAPI가 `web/`을 `/`로 서빙하므로 `/img/seasons/...`입니다.
