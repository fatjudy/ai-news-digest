import os
from dotenv import load_dotenv
import requests
import smtplib
import ssl
from email.message import EmailMessage
import config

load_dotenv()


def fetch_papers():
    """Fetch recent papers from arXiv for the categories in config.ARXIV_CATEGORIES."""
    pass


def fetch_repos():
    """Fetch trending AI/ML repos from GitHub using config.GITHUB_TOPICS."""
    pass


def fetch_news() -> list:
    """Fetch recent news from Hacker News using the public Firebase API.

    Returns a list of dicts with keys: `title`, `url`, `by`, `time`, `id`.
    """
    try:
        top_resp = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
        top_resp.raise_for_status()
        ids = top_resp.json()
    except Exception:
        return []

    stories = []
    max_items = getattr(config, "NEWS_MAX_ARTICLES", 10)
    for story_id in ids[:max_items]:
        try:
            item_resp = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=10)
            item_resp.raise_for_status()
            item = item_resp.json() or {}
            stories.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "url": item.get("url"),
                "by": item.get("by"),
                "time": item.get("time"),
            })
        except Exception:
            continue
    return stories


def summarize(content: dict) -> str:
    """Summarize fetched content into a digest using the Anthropic API.

    If no summarization is available, return an empty string to allow
    the caller to build a fallback digest.
    """
    return ""


def send_email(subject: str, body: str) -> None:
    """Send the digest email via Gmail SMTP using an app password.

    Environment variables used:
    - `GMAIL_USER` : the Gmail address to send from
    - `GMAIL_APP_PASSWORD` : the Gmail app password
    - `TO_EMAIL` : recipient address
    """
    gmail_user = os.getenv("GMAIL_USER")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    to_email = os.getenv("TO_EMAIL")

    if not gmail_user or not gmail_app_password or not to_email:
        print("Missing Gmail SMTP configuration; email not sent.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.set_content(body or "")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(gmail_user, gmail_app_password)
            server.send_message(msg)
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")


def main():
    papers = fetch_papers()
    repos = fetch_repos()
    news = fetch_news()

    digest = summarize({"papers": papers, "repos": repos, "news": news})
    if not digest:
        lines = []
        if news:
            lines.append("Top Hacker News stories:\n")
            for n in news:
                title = n.get("title") or "(no title)"
                url = n.get("url") or f"https://news.ycombinator.com/item?id={n.get('id')}"
                by = n.get("by")
                lines.append(f"- {title} ({url}) by {by}")
        else:
            lines.append("No news found.")
        digest = "\n".join(lines)

    send_email(config.DIGEST_SUBJECT, digest)


if __name__ == "__main__":
    main()
