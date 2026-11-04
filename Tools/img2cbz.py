import os
import zipfile

from loguru import logger


def images_to_cbz(image_files, cbz_output_path):
    """Pack the page images into a .cbz (zip).  Returns None on success or the error."""
    try:
        with zipfile.ZipFile(cbz_output_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for image_file_path in image_files:
                zip_file.write(image_file_path, arcname=os.path.basename(image_file_path))

        logger.info(f"CBZ created at {cbz_output_path}")
        return None
    except Exception as e:
        logger.exception(f"Making CBZ: {e}")
        if os.path.exists(cbz_output_path):
            os.remove(cbz_output_path)
        return e
