"""Deterministic original activity fixtures for offline print QA, not production fallback."""
from core.activity_generator import validate_pack
from pathlib import Path
from PIL import Image, ImageDraw


def attach_test_art(pack: dict, folder: str) -> dict:
    """Attach explicitly synthetic plant art for offline layout checks, never production."""
    path = Path(folder) / 'test-plant.png'
    image = Image.new('RGB', (400, 300), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((200, 220, 200, 90), fill='#267A54', width=12)
    draw.ellipse((110, 80, 202, 145), fill='#49B67E')
    draw.ellipse((195, 120, 295, 185), fill='#267A54')
    draw.polygon([(150, 210), (250, 210), (230, 280), (170, 280)], fill='#E89658')
    image.save(path)
    for page in pack['pages']:
        page['art'] = str(path)
        for item in page['items']:
            item.update(art=str(path), left_art=str(path), right_art=str(path))
    return pack


def sample_pack(band: str, config: dict) -> dict:
    """Create varied complete exercises to test the renderer without AI credentials."""
    young = band == "Pre-K-K"
    count = config["items_per_page"]
    kinds = ["count", "matching", "sort", "draw", "trace", "count"] if young else ["arithmetic", "matching", "sort", "reading", "draw", "reading", "arithmetic", "draw"]
    pages = []
    for index in range(config["activity_pages"]):
        kind = kinds[index % len(kinds)]
        page = dict(type=kind, title=f"Garden Lab {index+1}: {kind.title()}",
                    objective="Observe details and explain a useful connection.",
                    instructions="Look closely. Complete the task and share your thinking with a partner.",
                    teacher_tip="Model the first task. Invite a student to explain a strategy before working independently.",
                    support="Read directions aloud and work through one example with the student.",
                    extension="Create another example and explain how to solve it.", minutes=10, items=[])
        if kind == "count":
            page["items"] = [{"icon": k, "count": n} for k, n in [("leaf", 5), ("star", 8), ("book", 10)][:count]]
        elif kind == "arithmetic":
            page["items"] = [{"a": 12 + i, "b": 3 + i, "op": "+"} for i in range(count)]
        elif kind == "matching":
            pairs = [("Seed", "Starts a new plant"), ("Roots", "Take in water"), ("Stem", "Supports the leaves"), ("Leaf", "Uses light to help make food")]
            page["items"] = [dict(left=a, right=b) for a, b in pairs[:count]]
        elif kind == "sort":
            page["categories"] = ["Garden tools", "Plant parts"]
            page["items"] = [dict(label=a, category=b) for a, b in [("Hand shovel", 0), ("Leaf", 1), ("Watering can", 0), ("Root", 1)][:count]]
        elif kind == "reading":
            page["passage"] = ("A class tested two garden beds. Each bed had the same kind of soil and the same number of seeds. "
                               "The students gave both beds equal amounts of water. One bed received more sunlight. "
                               "They measured plant height each Friday and recorded their observations. After four weeks, "
                               "they compared the measurements to look for a pattern.")
            page["items"] = [dict(question=q, answer=a) for q, a in [
                ("What did the class change between the beds?", "The amount of sunlight."),
                ("Name two things the class kept the same.", "Soil type, number of seeds, and amount of water were kept the same; any two."),
                ("When did the students measure height?", "Each Friday."),
                ("Why record the measurements?", "To compare the beds over time and look for a pattern.")][:count]]
        elif kind == "trace":
            page["items"] = [{"word": w} for w in ["leaf", "seed", "sun", "root"][:count]]
        else:
            page.update(challenge="Design a small garden with a place for plants, a path for people, and access to water.",
                        criteria=["Include and label two plant areas.", "Keep a clear path to reach the plants.", "Explain where the water comes from."],
                        sample_response="Two plant beds beside a clear path, with a watering can near the entrance. Accept other designs meeting the criteria.")
        page['image_prompt'] = 'A classroom garden with seedlings, original educational art, no text.'
        for item in page['items']:
            item.update(image_prompt='One isolated plant on white.', left_image_prompt='A single plant on white.', right_image_prompt='A watering can on white.')
        pages.append(page)
    for index in (0, 1):
        pages[index].update(title=f'Garden Choices {index + 1}', type='picture_choice', items=[dict(question='What helps this plant grow?', choices=['Water it.', 'Hide it.', 'Pull it out.'], correct=0, image_prompt='A wilting garden plant in dry soil, no text.') for _ in range(count)])
    return validate_pack(dict(title="The Garden Ideas Lab", overview="A hands-on collection of observation, connection and design challenges for curious classroom thinkers.",
                              character_description='Original friendly students wearing teal and coral shirts.',
                              objectives=["Compare and classify information.", "Explain a choice using evidence or examples."],
                              materials=["Pencils and crayons", "Safety scissors with adult supervision"], pages=pages),
                         "Garden investigation", band, config)
