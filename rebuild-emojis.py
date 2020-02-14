#!/usr/bin/env python3
from emoji_parser import *
from PIL import Image
import os
import math
import argparse
from jinja2 import Environment, FileSystemLoader, Template


def twemoji_filenames(code_points: list):
    code_points = [f"{c:x}" for c in code_points]
    return [
        "-".join(code_points) + ".svg.png",
        "-".join([c for c in code_points if c != "fe0f"]) + ".svg.png",
    ]


def openmoji_filenames(code_points: list):
    code_points = [f"{c:0{4}X}" for c in code_points]
    return [
        "-".join(code_points) + ".svg.png",
        "-".join([c for c in code_points if c != "FE0F"]) + ".svg.png",
    ]


def noto_filenames(code_points: list):
    code_points = [f"{c:0{4}x}" for c in code_points]
    return [
        "emoji_u" + "_".join(code_points) + ".svg.png",
        "emoji_u" + "_".join(code_points) + ".png",
        "emoji_u" + "_".join([c for c in code_points if c != "fe0f"]) + ".svg.png",
        "emoji_u" + "_".join([c for c in code_points if c != "fe0f"]) + ".png",
    ]


def load_emoji(code_points: list, emoji_dir, emoji_filenames):
    for emoji_filename in emoji_filenames(code_points):
        emoji_filepath = os.path.join(emoji_dir, emoji_filename)
        if os.path.isfile(emoji_filepath):
            return Image.open(emoji_filepath)
    print("failed to load emoji: " + emoji_filename)


def get_pages(emojis):
    # we use this to strip variations
    components = [0x1F3FB, 0x1F3FC, 0x1F3FD, 0x1F3FE, 0x1F3FF]

    pages = {}
    for group in [g for g in Group if g != Group.COMPONENT]:
        pages[group.name] = []

    def find_parent_emoji_index(emoji: Emoji):
        parent_code_points = [
            [c for c in emoji.codePoints if c not in components],
            [0xFE0F if c in components else c for c in emoji.codePoints],
        ]
        for idx, e in enumerate(pages[emoji.group.name]):
            if e[0] in parent_code_points:
                return idx

        return None


    failed_count = 0
    for emoji in filter(lambda e: e.status == Status.FULLY_QUALIFIED and e.group != Group.COMPONENT, result.emoji):
        print(f"{emoji.name}: {codepoint_to_str(emoji.codePoints)}")
        if emoji.skinTones != [SkinTone.NONE]:
            # search for the parent emoji
            idx = find_parent_emoji_index(emoji)
            if not idx:
                failed_count = failed_count + 1
                continue
            pages[emoji.group.name][idx].append(emoji.codePoints)
        else:
            pages[emoji.group.name].append(
                [emoji.codePoints]
            )

    return pages


def codepoint_to_str(code_point):
    return " ".join([f"{c:0{4}X}" for c in code_point])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="process emoji PNGs of size 64x64 and generates sprites and Java class for Signal-Android"
    )
    parser.add_argument("--signal-repo-path", required=True)
    parser.add_argument(
        "--emojis", choices=["twemoji", "openmoji", "noto"], required=True
    )
    args = parser.parse_args()

    if args.emojis == "twemoji":
        emoji_filenames = twemoji_filenames
    elif args.emojis == "openmoji":
        emoji_filenames = openmoji_filenames
    elif args.emojis == "noto":
        emoji_filenames = noto_filenames

    env = Environment(loader=FileSystemLoader(searchpath="./"))
    template = env.get_template("EmojiPages.java.jinja2")

    # from https://unicode.org/Public/emoji/12.0/emoji-test.txt
    parser = EmojiParser(filepath="emoji-test.txt")
    result = parser.parse()

    # grid is max 32x12, so 384 emojis
    columns = 32
    max_rows = 12

    # get all emoji pages
    pages = get_pages(result.emoji)

    # chunk in smaller blocks of 384 emojis
    chunk_size = columns * max_rows
    all_page_chunks = {}
    for group, page in pages.items():
        count = 0
        chunk_idx = 0
        chunks = [[]]
        for emoji in page:
            if not load_emoji(emoji[0], args.emojis, emoji_filenames):
                print("skipping emoji because I can't load it")
            count += len(emoji)
            if count >= chunk_size:
                chunks.append([])
                chunk_idx += 1
                count = 0
            chunks[chunk_idx].append(emoji)

        all_page_chunks[group] = chunks

    # create sprite sheets
    for group, page_chunks in all_page_chunks.items():
        for chunk_idx, page_chunk_emojis in enumerate(page_chunks):
            sprite_sheet_emojis = [item for sublist in page_chunk_emojis for item in sublist]
            sprite_sheet_filename = f"{group.lower()}_{chunk_idx}.webp"
            width = columns * 64
            height = math.ceil(len(sprite_sheet_emojis) / columns) * 64
            print(
                f"creating {sprite_sheet_filename} from {len(sprite_sheet_emojis)} main emojis of {width}x{height}px"
            )
            sprite_sheet = Image.new("RGBA", (width, height))

            for (i, emoji) in enumerate(sprite_sheet_emojis):
                image = load_emoji(emoji, args.emojis, emoji_filenames)
                if image:
                    column = i % columns
                    row = math.floor(i / columns)
                    sprite_sheet.paste(image, (column * 64, row * 64))

            sprite_sheet.save(
                os.path.join(
                    args.signal_repo_path,
                    "app/src/main/assets/emoji",
                    sprite_sheet_filename,
                )
            )

    java_file_path = os.path.join(
        args.signal_repo_path,
        "app/src/main/java/org/thoughtcrime/securesms/components/emoji/EmojiPages.java",
    )
    java_file_content = template.stream(all_page_chunks=all_page_chunks).dump(java_file_path)
