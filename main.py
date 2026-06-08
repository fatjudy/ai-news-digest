import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import requests
import smtplib
import ssl
from email.message import EmailMessage
import anthropic
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


def fetch_repos() -> list:
    """Fetch trending AI/ML repos from GitHub using config.GITHUB_TOPICS.

    Returns a list of dicts with: name, description, stars, url.
    """
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("Missing GITHUB_TOKEN in environment; fetch_repos cannot run.")
        return []

    topics = getattr(config, "GITHUB_TOPICS", ["machine-learning", "deep-learning", "llm"])
    max_repos = getattr(config, "GITHUB_MAX_REPOS", 10)

    if topics:
        topic_query = " ".join([f"topic:{topic}" for topic in topics])
    else:
        topic_query = ""

    one_week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    query_parts = [topic_query, f"pushed:>={one_week_ago}"]
    query = " ".join(part for part in query_parts if part).strip()

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {github_token}",
    }
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": max_repos,
    }

    try:
        response = requests.get("https://api.github.com/search/repositories", headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        repos = []
        for item in data.get("items", []):
            repos.append({
                "name": item.get("full_name"),
                "description": item.get("description") or "",
                "stars": item.get("stargazers_count", 0),
                "url": item.get("html_url"),
            })
        return repos
    except Exception as exc:
        print(f"GitHub repo search failed: {exc}")
        return []


def fetch_news() -> list:
    """Fetch recent AI/ML news from Hacker News top and new stories.

    Returns a list of dicts with: title, url, points.
    """
    keywords = [
        "ai",
        "ml",
        "llm",
        "machine learning",
        "deep learning",
        "artificial intelligence",
        "neural network",
        "transformer",
        "transformers",
    ]
    max_items = getattr(config, "NEWS_MAX_ARTICLES", 20)
    story_ids = []

    def load_ids(endpoint: str):
        try:
            resp = requests.get(endpoint, timeout=10)
            resp.raise_for_status()
            return resp.json() or []
        except Exception:
            return []

    top_ids = load_ids("https://hacker-news.firebaseio.com/v0/topstories.json")
    new_ids = load_ids("https://hacker-news.firebaseio.com/v0/newstories.json")

    seen = set()
    for story_id in top_ids + new_ids:
        if story_id in seen:
            continue
        seen.add(story_id)
        story_ids.append(story_id)
        if len(story_ids) >= max_items:
            break

    filtered = []
    for story_id in story_ids:
        try:
            item_resp = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=10)
            item_resp.raise_for_status()
            item = item_resp.json() or {}
            title = (item.get("title") or "").lower()
            if not title:
                continue

            if any(keyword in title for keyword in keywords):
                filtered.append({
                    "title": item.get("title"),
                    "url": item.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                    "points": item.get("score", 0),
                })
        except Exception:
            continue

    return filtered


def summarize(content: dict) -> str:
    """Summarize fetched content into a weekly digest using Anthropic.

    Returns a concise HTML digest grouped into three sections for a data scientist.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Missing ANTHROPIC_API_KEY in environment; cannot summarize.")
        return ""

    papers = content.get("papers", []) or []
    repos = content.get("repos", []) or []
    news = content.get("news", []) or []

    def format_items(items, item_keys):
        if not items:
            return "<p>No entries found this week.</p>"
        formatted = ""
        for item in items:
            values = [str(item.get(k, "")).strip() for k in item_keys if item.get(k) is not None]
            formatted += "<li>" + " — ".join(values) + "</li>"
        return f"<ul>{formatted}</ul>"

    paper_section = format_items(papers, ["title", "authors", "link"])
    repo_section = format_items(repos, ["name", "description", "stars", "url"])
    news_section = format_items(news, ["title", "points", "url"])

    prompt = f"""
You are a helpful assistant that writes concise weekly digests for data scientists.
Produce a short HTML document with three sections: Papers, Repositories, and News.
Each section should have a heading and a short summary of why the content matters.
Use valid HTML only, without markdown, code fences, or extra commentary.
Include only the digest markup in the response.

Papers:
{paper_section}

Repositories:
{repo_section}

News:
{news_section}

Return the digest as HTML. Use headings, paragraphs, and lists. Keep it concise.
"""

    client = anthropic.Client(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            system="You are a concise summarization assistant for data scientists.",
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            max_tokens=800,
            temperature=0.2,
        )
        content_blocks = getattr(response, "content", [])
        if not content_blocks:
            return str(response)
        return "".join(getattr(block, "text", "") for block in content_blocks)
    except Exception as exc:
        print(f"Anthropic summarization failed: {exc}")
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
