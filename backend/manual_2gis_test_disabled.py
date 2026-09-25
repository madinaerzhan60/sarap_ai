import asyncio
import json
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


URL = "https://2gis.kz/almaty/firm/70000001082736602/tab/reviews"


def parse_reviews(html: str):
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select("div._1rowqpjv")

    reviews = []

    for i, card in enumerate(cards):
        author = card.select_one("span[title]")
        date = card.select_one("span._10c0hgu")
        text = card.select_one("div._83kmcy a")

        stars = card.select('svg[color="#ffb81c"]')

        if not text:
            continue

        review_text = text.get_text(" ", strip=True)

        if not review_text:
            continue

        reviews.append(
            {
                "external_id": f"2gis-{i}-{author.get_text(' ', strip=True) if author else 'unknown'}",
                "source": "2GIS",
                "author": author.get_text(" ", strip=True) if author else "Unknown",
                "date_raw": date.get_text(" ", strip=True) if date else None,
                "text": review_text,
                "rating": min(len(stars), 5) if stars else None,
                "url": URL,
            }
        )

    return reviews


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=".sarap-browser-profile",
            channel="chrome",
            headless=False,
            locale="ru-KZ",
            timezone_id="Asia/Almaty",
            viewport={
                "width": 1280,
                "height": 900,
            },
        )

        page = (
            context.pages[0]
            if context.pages
            else await context.new_page()
        )

        await page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print("\nChrome opened.")
        print("Если есть verification — пройди её.")
        print("Убедись, что видишь отзывы.")
        print("После этого нажми ENTER здесь.\n")

        await asyncio.to_thread(input)

        previous_count = 0
        stagnant = 0

        for i in range(40):
            html = await page.content()
            reviews = parse_reviews(html)

            current_count = len(reviews)

            print(
                f"Scroll {i + 1}: {current_count} reviews"
            )

            if current_count == previous_count:
                stagnant += 1
            else:
                stagnant = 0

            if current_count >= 66:
                break

            if stagnant >= 6:
                break

            previous_count = current_count

            cards = page.locator("div._1rowqpjv")

            if await cards.count():
                await cards.last.scroll_into_view_if_needed()

            await page.mouse.wheel(
                0,
                1800,
            )

            await page.wait_for_timeout(
                1200
            )

        html = await page.content()

        reviews = parse_reviews(html)

        # Remove duplicates
        unique = []
        seen = set()

        for review in reviews:
            key = (
                review["author"],
                review["date_raw"],
                review["text"],
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(review)

        with open(
            "2gis_reviews.json",
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                unique,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print("\n======================")
        print("TOTAL SAVED:", len(unique))
        print("======================\n")

        for review in unique[:5]:
            print(
                review["author"],
                "|",
                review["rating"],
                "|",
                review["text"][:100],
            )

        print(
            "\nSaved to backend/2gis_reviews.json"
        )

        print(
            "\nНажми ENTER чтобы закрыть Chrome."
        )

        await asyncio.to_thread(input)

        await context.close()


asyncio.run(main())