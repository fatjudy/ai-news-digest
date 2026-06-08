import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import requests
import smtplib
import ssl
from email.message import EmailMessage
import arxiv
import config

load_dotenv()


def fetch_papers() -> list:
    """Fetch recent papers from arXiv in the last 7 days and attach citation counts.

    Returns a list of dicts with: title, authors, abstract, link, citation_count.
    """
    categories = getattr(config, "ARXIV_CATEGORIES", ["cs.AI", "cs.LG", "cs.CL"])
    max_results = getattr(config, "ARXIV_MAX_RESULTS", 20)
    query = " OR ".join([f"cat:{cat}" for cat in categories])
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    client = arxiv.Client()
    papers = []
    for result in client.results(search):
        if result.published is None or result.published < cutoff:
            continue

        arxiv_id = result.entry_id.rsplit("/", 1)[-1]
        citation_count = _fetch_semantic_scholar_citations(arxiv_id)
        papers.append({
            "title": result.title,
            "authors": [author.name for author in result.authors],
            "abstract": result.summary,
            "link": result.pdf_url or result.entry_id,
            "citation_count": citation_count,
        })

    return papers


def _fetch_semantic_scholar_citations(arxiv_id: str) -> int:
    endpoint = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields=citationCount"
    try:
        resp = requests.get(endpoint, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return int(data.get("citationCount", 0))
    except Exception:
        return 0


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
