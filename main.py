import os
import feedparser
import requests
import deepl
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# 가져올 RSS 피드 주소 목록
KOREAN_FEEDS = {
    "GeekNews": "https://feeds.feedburner.com/geeknews-feed",
    "무신사": "https://medium.com/feed/musinsa-tech",
    "네이버": "https://d2.naver.com/d2.atom",
    "카카오": "https://tech.kakao.com/feed/",
    "토스": "https://toss.tech/rss.xml",
    "NHN Toast": "https://meetup.toast.com/rss",
}

FOREIGN_FEEDS = {
    "Hacker News": "https://hnrss.org/frontpage",
}

# GitHub Secrets에서 API 키와 웹훅 URL 가져오기
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY")

# --- 번역기 설정 ---
try:
    translator = deepl.Translator(DEEPL_API_KEY)
except Exception as e:
    print(f"DeepL 번역기 초기화 오류: {e}")
    translator = None

def translate_text(text):
    """DeepL API를 사용하여 텍스트를 한국어로 번역합니다."""
    if not translator or not text:
        return "번역 실패 (API 키 또는 텍스트를 확인하세요)"
    try:
        # 무료 API는 'EN-US' 대신 'EN' 사용
        result = translator.translate_text(text, target_lang="KO")
        return result.text
    except Exception as e:
        print(f"DeepL 번역 오류: {e}")
        return f"번역 중 오류 발생: {text[:50]}..."

# --- RSS 피드 파싱 ---
def get_latest_news(feed_url):
    """RSS 피드에서 최신 소식을 가져옵니다 (지난 24시간)."""
    try:
        feed = feedparser.parse(feed_url)
        yesterday = datetime.now() - timedelta(days=1)
        
        recent_entries = []
        for entry in feed.entries:
            published_time = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else datetime.now()
            if published_time >= yesterday:
                recent_entries.append(entry)
        # 너무 많은 메시지를 보내지 않도록 최신 2개로 제한
        return recent_entries[:2]
    except Exception as e:
        print(f"RSS 피드 '{feed_url}'를 가져오는 중 오류: {e}")
        return []

# --- 슬랙 메시지 생성 ---
def create_slack_message(news_items):
    """
    Slack Block Kit을 사용하여 UI 예시처럼 카드형 뉴스 리스트를 만듭니다.
    item['text']: 뉴스 제목/요약 등 (mrkdwn)
    item['site']: 사이트명
    item['url']: 뉴스 원문 링크
    item['meta']: 부가정보(시간/조회/댓글 등)
    """
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📑 오늘의 주요 뉴스 (상위 {len(news_items)})",
                "emoji": True
            }
        }
    ]

    if not news_items:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "지난 24시간 동안 새로운 소식이 없습니다."}
        })
        return {"blocks": blocks}

    for item in news_items:
        # 뉴스카드(구분선+섹션)
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{item['site']}*\n{item['text']}\n_{item['meta']}_"
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "읽기"},
                "url": item["url"]
            }
        })
        if len(blocks) > 45:
            break

    return {"blocks": blocks}


def send_to_slack(message_payload):
    """생성된 메시지를 슬랙 웹훅으로 전송합니다."""
    if not SLACK_WEBHOOK_URL:
        print("슬랙 웹훅 URL이 설정되지 않았습니다.")
        return
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=message_payload, timeout=10)
        response.raise_for_status()
        print("슬랙으로 메시지를 성공적으로 보냈습니다.")
    except requests.exceptions.RequestException as e:
        print(f"슬랙 전송 오류: {e}")

# --- 메인 실행 로직 ---
def main():
    if not SLACK_WEBHOOK_URL or not DEEPL_API_KEY:
        print("오류: SLACK_WEBHOOK_URL 또는 DEEPL_API_KEY 환경 변수가 설정되지 않았습니다.")
        return

    all_news = []

    # 국내 뉴스 수집
    for name, url in KOREAN_FEEDS.items():
        print(f"국내 뉴스 수집 중: {name}")
        for entry in get_latest_news(url):
            # 부가정보(meta) 예시 (published, 조회수, 댓글수 모두 optional)
            published = entry.get('published', '')[:16]  # 없으면 ''
            # GeekNews 등은 summary에 조회수/댓글수가 있을 수도 있음
            summary = entry.get('summary', '')
            import re
            views = re.search(r'조회수\s?([0-9.,Kk]+)', summary)
            comments = re.search(r'댓글\s?([0-9.,Kk]+)', summary)
            views = views.group(1) if views else ''
            comments = comments.group(1) if comments else ''
            # meta 조립
            meta = published
            if views:
                meta += f" · 조회수 {views}"
            if comments:
                meta += f" · 댓글 {comments}"
            # 뉴스 dict 만들기
            all_news.append({
                "site": name,
                "text": entry.title,
                "meta": meta.strip(),
                "url": entry.link
            })

    # 해외 뉴스 수집 및 번역
    for name, url in FOREIGN_FEEDS.items():
        print(f"해외 뉴스 수집 중: {name}")
        for entry in get_latest_news(url):
            published = entry.get('published', '')[:16]
            meta = published
            all_news.append({
                "site": name,
                "text": translate_text(entry.title),
                "meta": meta.strip(),
                "url": entry.link
            })
    
    if not all_news:
        print("지난 24시간 동안 수집된 새 소식이 없습니다.")
    
    slack_payload = create_slack_message(all_news)
    send_to_slack(slack_payload)

if __name__ == "__main__":
    main()
