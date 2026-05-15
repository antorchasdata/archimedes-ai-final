"""
Export Archimedes AI HTML presentation to PDF — screenshot each slide.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

HTML_PATH = Path(__file__).parent / "Archimedes_AI_Presentation.html"
PDF_PATH  = Path(__file__).parent / "Archimedes_AI_Presentation.pdf"
TOTAL_SLIDES = 21
W, H = 1280, 720

async def main():
    screenshots = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": W, "height": H})

        await page.goto(f"file://{HTML_PATH.resolve()}")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2.5)  # fonts + remote images on slide 1

        for i in range(TOTAL_SLIDES):
            if i == 0:
                # slide 1 is already active on load — no goTo needed
                await asyncio.sleep(0.3)
            else:
                await page.evaluate(f"goTo({i})")
                await asyncio.sleep(0.5)
            img_path = HTML_PATH.parent / f"_slide_{i:02d}.png"
            await page.screenshot(path=str(img_path), full_page=False)
            screenshots.append(img_path)
            print(f"  Screenshot {i+1}/{TOTAL_SLIDES}")

        await browser.close()

    # Combine PNGs into PDF with Pillow
    from PIL import Image
    images = [Image.open(p).convert("RGB") for p in screenshots]
    images[0].save(
        str(PDF_PATH),
        save_all=True,
        append_images=images[1:],
        resolution=150,
    )

    # Clean up temp PNGs
    for p in screenshots:
        p.unlink()

    print(f"\n✓ PDF saved: {PDF_PATH}")

asyncio.run(main())
