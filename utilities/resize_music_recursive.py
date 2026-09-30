import io
import logging
import os
from pathlib import Path

import click
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

try:
    # Canonical extension list from the shared suite config; the fallback
    # below is used ONLY when running outside an installed suite environment.
    from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

    AUDIO_EXTENSIONS = set(SUPPORTED_EXTENSIONS)
except ImportError:
    AUDIO_EXTENSIONS = {
        ".mp3",
        ".flac",
        ".ogg",
        ".m4a",
        ".mp4",
        ".opus",
        ".wav",
        ".aiff",
        ".aif",
    }


def resize_image_bytes(image_bytes: bytes, target_size: int) -> bytes | None:
    """Resizes image bytes to a square target size while preserving aspect ratio."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        # Crops and scales cleanly into a perfect square
        resized_img = ImageOps.fit(
            img, (target_size, target_size), Image.Resampling.LANCZOS
        )

        output = io.BytesIO()
        resized_img.save(output, format="JPEG", quality=90)
        return output.getvalue()
    except (OSError, ValueError) as e:
        click.echo(click.style(f"  [!] Error resizing image bytes: {e}", fg="red"))
        return None


def extract_embedded_art_bytes(
    file_path: Path,
) -> bytes | None:
    """Extracts raw image bytes from the first available artwork frame."""
    try:
        audio = File(file_path)
        if audio is None or audio.tags is None:
            return None

        # MP3 Files (ID3 Tags)
        if isinstance(audio, MP3) or hasattr(audio.tags, "add"):
            for key in audio.tags.keys():
                if key.startswith("APIC"):
                    return audio.tags[key].data

        # FLAC Files
        elif isinstance(audio, FLAC) and audio.pictures:
            return audio.pictures[0].data

        # MP4 / M4A / AAC Files
        elif isinstance(audio, MP4) and "covr" in audio.tags:
            covers = audio.tags["covr"]
            if covers:
                return covers[
                    0
                ]  # Returns bytes or MP4Cover object (which behaves like bytes)

    except (OSError, ValueError) as e:
        click.echo(
            click.style(
                f"  [!] Error extracting art from {file_path.name}: {e}", fg="red"
            )
        )
    return None


def process_or_create_folder_jpg(directory: Path, audio_files: list[Path]) -> bool:
    """
    Resizes folder.jpg to 1000x1000 if it exists.
    If missing, extracts embedded art from audio files to create a 1000x1000 folder.jpg.
    """
    valid_names = [
        "folder.jpg",
        "folder.jpeg",
        "Folder.jpg",
        "Folder.jpeg",
        "cover.jpg",
        "Cover.jpg",
    ]

    # 1. Check if an external image already exists
    for filename in valid_names:
        file_path = directory / filename
        if file_path.exists():
            try:
                img = Image.open(file_path)
                if img.size != (1000, 1000):
                    resized_img = ImageOps.fit(
                        img, (1000, 1000), Image.Resampling.LANCZOS
                    )
                    resized_img.save(
                        directory / "folder.jpg", format="JPEG", quality=90
                    )
                    click.echo(
                        click.style(
                            f"  [OK] Resized existing external art: {filename}",
                            fg="green",
                        )
                    )
                return True
            except OSError as e:
                click.echo(
                    click.style(
                        f"  [X] Failed to resize existing {filename}: {e}", fg="red"
                    )
                )
                return False

    # 2. If no folder.jpg exists, try to extract art from local audio files
    for audio_file in audio_files:
        art_bytes = extract_embedded_art_bytes(audio_file)
        if art_bytes:
            resized_bytes = resize_image_bytes(art_bytes, 1000)
            if resized_bytes:
                try:
                    dest_path = directory / "folder.jpg"
                    with open(dest_path, "wb") as f:
                        f.write(resized_bytes)
                    click.echo(
                        click.style(
                            "  [CREATED] Created missing folder.jpg"
                            f" from {audio_file.name}",
                            fg="yellow",
                        )
                    )
                    return True
                except OSError as e:
                    click.echo(
                        click.style(
                            f"  [X] Failed to write extracted folder.jpg: {e}", fg="red"
                        )
                    )
                    return False
    return False


def resize_embedded_art(file_path: Path, target_size: int) -> bool:
    """Resizes the embedded artwork of an audio file without losing other tags."""
    try:
        audio = File(file_path)
        if audio is None or audio.tags is None:
            return False

        modified = False

        # MP3 Files (ID3 Tags)
        if isinstance(audio, MP3) or hasattr(audio.tags, "add"):
            for key in list(audio.tags.keys()):
                if key.startswith("APIC"):
                    apic = audio.tags[key]
                    try:
                        img = Image.open(io.BytesIO(apic.data))
                        if img.size == (target_size, target_size):
                            continue
                    except (UnidentifiedImageError, OSError):
                        # A frame PIL cannot decode cannot be size-checked, so
                        # falling through to the resize is the safe action; the
                        # silence was the defect. UnidentifiedImageError is a
                        # subclass of OSError, so this tuple names both the
                        # unidentifiable and the truncated cases explicitly.
                        logger.debug(
                            "Embedded frame %s of %s is not decodable as an "
                            "image; treating it as not-at-target-size and "
                            "resizing",
                            key,
                            file_path,
                            exc_info=True,
                        )

                    resized_data = resize_image_bytes(apic.data, target_size)
                    if resized_data:
                        audio.tags[key] = APIC(
                            encoding=3,
                            mime="image/jpeg",
                            type=apic.type,
                            desc=apic.desc,
                            data=resized_data,
                        )
                        modified = True

        # FLAC Files
        elif isinstance(audio, FLAC):
            new_pictures = []
            for pic in audio.pictures:
                if pic.width == target_size and pic.height == target_size:
                    new_pictures.append(pic)
                    continue

                resized_data = resize_image_bytes(pic.data, target_size)
                if resized_data:
                    new_pic = Picture()
                    new_pic.data = resized_data
                    new_pic.type = pic.type
                    new_pic.mime = "image/jpeg"
                    new_pic.description = pic.description
                    new_pic.width = target_size
                    new_pic.height = target_size
                    new_pic.depth = 24
                    new_pictures.append(new_pic)
                    modified = True
                else:
                    new_pictures.append(pic)
            if modified:
                audio.clear_pictures()
                for n_pic in new_pictures:
                    audio.add_picture(n_pic)

        # MP4 / M4A / AAC Files
        elif isinstance(audio, MP4):
            if "covr" in audio.tags:
                covers = audio.tags["covr"]
                new_covers = []
                for cover in covers:
                    resized_data = resize_image_bytes(cover, target_size)
                    if resized_data:
                        new_covers.append(
                            MP4Cover(resized_data, imageformat=MP4Cover.FORMAT_JPEG)
                        )
                        modified = True
                    else:
                        new_covers.append(cover)
                if modified:
                    audio.tags["covr"] = new_covers

        if modified:
            audio.save()
            return True

    except (OSError, ValueError) as e:
        click.echo(
            click.style(
                f"  [!] Error processing tags for {file_path.name}: {e}", fg="yellow"
            )
        )

    return False


@click.command()
@click.argument(
    "start_dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--size",
    type=click.Choice(["600", "800", "1000", "1200"]),
    required=True,
    help="Target size for the embedded album artwork.",
)
def main(start_dir: Path, size: str) -> None:
    """
    Recursively crawls START_DIR and sub-directories.
    Optimizes or generates 'folder.jpg' (1000x1000) and scales embedded music artwork.
    """
    target_size = int(size)

    click.echo(
        click.style(
            f"\n[START] Starting recursive scan from: {start_dir}", fg="cyan", bold=True
        )
    )
    click.echo(
        click.style(
            f"[CONFIG] Target size: {target_size}x{target_size}"
            " | Folder.jpg: 1000x1000\n",
            fg="cyan",
        )
    )

    files_updated = 0
    folders_updated = 0

    for root, dirs, files in os.walk(start_dir):
        current_dir = Path(root)

        # Cleaner directory printing
        try:
            display_path = current_dir.relative_to(start_dir)
            display_name = (
                f"./{display_path}" if str(display_path) != "." else "Root Directory"
            )
        except ValueError:
            display_name = str(current_dir)

        # Filter out audio files present in this specific directory loop
        local_audio_files = [
            current_dir / f for f in files if Path(f).suffix.lower() in AUDIO_EXTENSIONS
        ]

        if local_audio_files or (current_dir / "folder.jpg").exists():
            click.echo(click.style(f"Scanning: {display_name}", fg="white", dim=True))

            # 1. Process existing folder.jpg OR create it from embedded tracks
            if process_or_create_folder_jpg(current_dir, local_audio_files):
                folders_updated += 1

            # 2. Resize embedded tags
            for file_path in local_audio_files:
                if resize_embedded_art(file_path, target_size):
                    click.echo(
                        click.style(
                            f"  [OK] Updated tags: {file_path.name}",
                            fg="green",
                        )
                    )
                    files_updated += 1

    # Print Summary
    click.echo(click.style("\n" + "=" * 40, fg="cyan"))
    click.echo(click.style("[DONE] Processing complete!", fg="green", bold=True))
    click.echo(f"[FOLDERS] External art processed: {folders_updated}")
    click.echo(f"[FILES] Embedded art updated: {files_updated}")
    click.echo(click.style("=" * 40, fg="cyan"))


if __name__ == "__main__":
    main()
