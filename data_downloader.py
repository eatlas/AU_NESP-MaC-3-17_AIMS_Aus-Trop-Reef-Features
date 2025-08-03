import urllib.request
import os
import sys
import time
import zipfile
import tempfile
import shutil
import glob
from typing import List


class DataDownloader:
    """
    This dataset class is designed to make downloading and unzipping datasets easier.
    The DataDownloader class provides methods for:
      1. Downloading files from a URL with a progress indicator.
      2. Unzipping downloaded files with optional directory checks and flattening.
      3. Moving/copying only a subset of files from a larger download.
    
    DataDownloader(download_path: str = "data-cache")
    - Creates a downloader object, storing downloaded data in `download_path`.

    download(url: str, path: str) -> None
    - Downloads a file from `url` to local `path` (skips if `path` exists).

    unzip(zip_file_path: str, unzip_path: str, path_test: str) -> None
    - Unzips `zip_file_path` into `unzip_path`, skipping if `path_test` subfolder already exists.

    download_and_unzip(url: str, dataset_name: str = None, subfolder_name: str = None, flatten_directory: bool = False) -> None
    - Downloads a ZIP from `url` and unpacks into `download_path/dataset_name[/subfolder_name]`.
    - If `flatten_directory` is True, moves nested files up one level.
    - If dataset_name is None, unzips directly to `download_path`.

    move_files(patterns: List[str], source_directory: str, destination_directory: str) -> None
    - Moves files from `source_directory` to `destination_directory`, matching each pattern in `patterns`.

    download_unzip_keep_subset(url: str, zip_file_patterns: List[str], dataset_name: str) -> None
    - Downloads a ZIP from `url`, unzips to a temp location, then moves only matching files to `download_path/dataset_name`.

    Class Attributes:
        start_time (float): Tracks the start time of the most recent download.
        last_report_time (float): Tracks the time of the last status update during a download.
        download_path (str): Local base directory for downloaded content.
        tmp_path (tempfile.TemporaryDirectory): Temporary directory object for intermediate operations.
    """

    def __init__(self, download_path: str = "data-cache") -> None:
        """
        Initializes the DataDownloader with an optional download path.

        :param download_path: Base directory where downloaded files are stored.
        """
        self.start_time = 0.0
        self.last_report_time = 0.0
        self.download_path = download_path
        self.tmp_path = tempfile.TemporaryDirectory()  # Holds temporary files during processing

    def _reporthook(self, count: int, block_size: int, total_size: int) -> None:
        """
        A hook function used by urllib.request.urlretrieve to display download progress.

        :param count: The current block count.
        :param block_size: The size of each block in bytes.
        :param total_size: The total size of the file in bytes (or -1 if unknown).
        """
        current_time = time.time()
        if count == 0:
            self.start_time = current_time
            self.last_report_time = current_time
            return
        time_since_last_report = current_time - self.last_report_time
        if time_since_last_report > 1:  # Update progress every 1 second
            self.last_report_time = current_time
            duration = current_time - self.start_time
            progress_size = int(count * block_size)
            speed = int(progress_size / (1024 * duration))

            if total_size != -1:
                percent = int(count * block_size * 100 / total_size)
                sys.stdout.write("%d%%, %d MB, %d KB/s, %d secs    \r" %
                                 (percent, progress_size / (1024 * 1024), speed, duration))
            else:
                sys.stdout.write("%d MB, %d KB/s, %d secs    \r" %
                                 (progress_size / (1024 * 1024), speed, duration))
            sys.stdout.flush()

    def _download(self, url: str, path: str) -> None:
        """
        Downloads a file from the given URL to the specified local path.

        If the target file already exists at the destination path, the function will skip the download.
        Otherwise, it downloads the file to a temporary location and then moves it to the desired path.
        During the download, a progress indicator is displayed via the `_reporthook` method.

        :param url: The URL of the file to be downloaded.
        :param path: The local path (including filename) where the file should be saved.
        """
        if os.path.exists(path):
            print(f"Skipping download of {path}; it already exists")
        else:
            print(f"Downloading from {url}")
            dest_dir = os.path.dirname(path)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
            tmp_path = path + '.tmp'

            # Define a set of headers to mimic a common browser request. This allows us
            # to download files from websites that may perform user agent checks or reject
            headers = {
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/58.0.3029.110 Safari/537.36"),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req) as response, open(tmp_path, 'wb') as out_file:
                total_size = response.getheader('Content-Length')
                total_size = int(total_size) if total_size is not None else -1
                block_size = 8192  # 8 KB block size
                count = 0
                self.start_time = time.time()
                self.last_report_time = time.time()
                while True:
                    chunk = response.read(block_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    count += 1
                    self._reporthook(count, block_size, total_size)
            os.rename(tmp_path, path)
            print("\nDownload complete")


    def unzip(self, zip_file_path: str, unzip_path: str, path_test: str) -> None:
        """
        Extracts the contents of a specified ZIP file to a designated directory.

        If the directory doesn't exist, it will be created. The function will skip 
        the extraction process if a specified sub-directory (given by `path_test`) 
        already exists within the target extraction directory, suggesting that the 
        unzip operation has likely already been performed.

        :param zip_file_path: Path to the ZIP file to be extracted.
        :param unzip_path: Path to the directory where the ZIP contents should be extracted.
        :param path_test: Sub-directory name (relative to unzip_path) to check as an 
                          indicator if the unzip operation has previously occurred.
        """
        # Normalize unzip_path to ensure no trailing slash
        unzip_path = os.path.normpath(unzip_path)
        unpack_dir = os.path.join(unzip_path, path_test)
        if os.path.exists(unpack_dir):
            print(f"Skipping unzip of {zip_file_path} as unzip path exists: {unpack_dir}")
        else:
            print(f"Unzipping {zip_file_path} to {unzip_path}")
            # Unzip to a temp directory that we rename at the end
            tmp_unzip_path = f'{unzip_path}_tmp'
            os.makedirs(tmp_unzip_path, exist_ok=True)
            absolute_unzip_path = os.path.abspath(tmp_unzip_path)

            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    full_path = os.path.join(absolute_unzip_path, member)
                    if len(full_path) > 260:
                        msg = (f"Extraction path too long for Windows (Max: 260 chars). "
                               f"It is {len(full_path)} characters. {full_path}")
                        raise ValueError(msg)
                zip_ref.extractall(tmp_unzip_path)

            # Rename the tmp_unzip_path to the final name
            os.rename(tmp_unzip_path, unzip_path)

    def download_only(self, 
                      url: str, 
                      dataset_name: str,
                      filename: str = None,
                      subfolder_name: str = None) -> None:
        """
        Downloads a file from the given URL and saves it into a folder based on 
        the dataset_name, and optionally a subfolder_name, using the download_path as the base path.

        :param url: URL to download the file from.
        :param dataset_name: The name of the dataset (used for directory naming).
        :param filename: Optional name to save the file as. If None, will extract from the URL.
        :param subfolder_name: Optional subfolder to differentiate between multiple downloads 
                               for the same dataset.
        """
        base_path = os.path.join(self.download_path, dataset_name)
        download_path = os.path.join(base_path, subfolder_name if subfolder_name else "")
        
        # Create the directory if it doesn't exist
        os.makedirs(download_path, exist_ok=True)
        
        # If filename is not provided, extract it from the URL
        if not filename:
            filename = url.split('/')[-1]
        
        file_path = os.path.join(download_path, filename)
        print(f"Download path: {file_path}")
        
        # Download the file directly to the final location
        self._download(url, file_path)

    def download_and_unzip(self, 
                           url: str, 
                           dataset_name: str = None, 
                           subfolder_name: str = None, 
                           flatten_directory: bool = False) -> None:
        """
        Downloads a ZIP file from the given URL and unpacks it.

        This method offers several ways to organize downloaded datasets:

        1. Basic dataset download (most common case):
           - Specify only `dataset_name` to download to `download_path/dataset_name/`
           - The script checks if this folder exists before downloading to avoid duplicates

        2. Multi-part dataset download:
           - Specify both `dataset_name` and `subfolder_name` to download to 
             `download_path/dataset_name/subfolder_name/`
           - Useful when a dataset has multiple components that should be organized together
           - Each subfolder is checked separately before downloading

        3. Direct download to root:
           - Set `dataset_name=None` to download directly to `download_path/`
           - Useful for special cases where you don't want an extra subfolder

        4. Handling nested directories in ZIP files:
           - Set `flatten_directory=True` to remove redundant top-level folders in the ZIP
           - When `dataset_name` and `subfolder_name` are specified, it looks for a folder named
             `subfolder_name` (or `dataset_name` if no subfolder) and flattens it
           - When `dataset_name=None`, it looks for a single top-level directory and flattens it
           - Flattening prevents deeply nested paths that can cause problems in Windows

        Examples:
            # Download "coastline" dataset to data-cache/coastline/
            downloader.download_and_unzip("https://example.com/coast.zip", "coastline")

            # Download "reefs-part1" to data-cache/reefs/part1/
            downloader.download_and_unzip("https://example.com/part1.zip", "reefs", "part1")

            # Download directly to data-cache/ and remove the top-level folder in the ZIP
            downloader.download_and_unzip("https://example.com/data.zip", None, flatten_directory=True)

            # Download "coastline" and remove redundant top folder from the zip
            downloader.download_and_unzip("https://example.com/coast.zip", "coastline", flatten_directory=True)

        :param url: URL to download the ZIP file from.
        :param dataset_name: The name of the dataset (used for directory naming).
                            If None, extracts directly to download_path.
        :param subfolder_name: Optional subfolder to differentiate between multiple downloads 
                              for the same dataset. Only used when dataset_name is provided.
        :param flatten_directory: If True, checks if the resulting directory has a subdirectory
                                 matching the dataset name or subfolder name, and moves its 
                                 contents up one level. When dataset_name is None, looks for a 
                                 single top-level directory to flatten.
        """
        if dataset_name is None:
            unzip_path = self.download_path
        else:
            base_path = os.path.join(self.download_path, dataset_name)
            unzip_path = os.path.join(base_path, subfolder_name if subfolder_name else "")
        
        print(f"Unzip folder: {unzip_path}")

        if os.path.exists(unzip_path) and os.listdir(unzip_path):  # Check if path exists and is not empty
            print(f"Skipping as unzip path exists and is not empty: {unzip_path}")
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download the ZIP file
                zip_file_name = f"{dataset_name or 'download'}.zip"
                zip_file_path = os.path.join(temp_dir, zip_file_name)
                self._download(url, zip_file_path)

                # Unzip the file
                self.unzip(zip_file_path, unzip_path, "")

        # Flatten the directory if requested
        if flatten_directory:
            self._flatten_directory(unzip_path, dataset_name, subfolder_name)

    def _flatten_directory(self, directory_path: str, dataset_name: str = None, subfolder_name: str = None) -> None:
        """
        Helper method to flatten a directory by moving all contents from a subdirectory up one level.
        
        If dataset_name is provided, looks for a subdirectory matching dataset_name or subfolder_name.
        If dataset_name is None, looks for any single top-level directory to flatten.
        
        :param directory_path: Path to the directory containing the subdirectory to flatten
        :param dataset_name: Optional name of the dataset to look for
        :param subfolder_name: Optional subfolder name to look for if dataset_name is provided
        """
        folder_to_flatten = None
        
        # Identify which folder to flatten
        if dataset_name is not None:
            # Check for specific folder based on dataset or subfolder name
            candidate = os.path.join(directory_path, subfolder_name if subfolder_name else dataset_name)
            if os.path.exists(candidate) and os.path.isdir(candidate):
                folder_to_flatten = candidate
                folder_name = subfolder_name if subfolder_name else dataset_name
        else:
            # Check for a single subdirectory when extracting to root
            subdirs = [d for d in os.listdir(directory_path) if os.path.isdir(os.path.join(directory_path, d))]
            if len(subdirs) == 1:
                folder_to_flatten = os.path.join(directory_path, subdirs[0])
                folder_name = subdirs[0]
        
        # If we found a folder to flatten, move its contents up and remove it
        if folder_to_flatten:
            print(f"Flattening directory: {folder_name}")
            
            # Move all files from the subdirectory to the parent directory
            for item in os.listdir(folder_to_flatten):
                source_path = os.path.join(folder_to_flatten, item)
                dest_path = os.path.join(directory_path, item)
                
                # Handle case where file/folder with same name already exists
                if os.path.exists(dest_path):
                    print(f"Warning: {item} already exists in destination. Skipping.")
                    continue
                    
                shutil.move(source_path, directory_path)
            
            # Remove the now empty subdirectory
            os.rmdir(folder_to_flatten)
            print(f"Flattening complete: removed {folder_name}")

    def move_files(self, 
                   patterns: List[str], 
                   source_directory: str, 
                   destination_directory: str) -> None:
        """
        Moves files from a source directory to a destination directory based on 
        the provided file-matching patterns.

        :param patterns: A list of file patterns (e.g., ["*.csv", "*.txt"]).
        :param source_directory: The directory to scan for files matching the patterns.
        :param destination_directory: The target directory to which the matched files will be moved.
        """
        if not os.path.exists(destination_directory):
            os.makedirs(destination_directory)
            print(f'Making destination directory {destination_directory}')

        # Find and move files matching the patterns
        for pattern in patterns:
            for filepath in glob.glob(os.path.join(source_directory, pattern)):
                filename = os.path.basename(filepath)
                destination_filepath = os.path.join(destination_directory, filename)
                shutil.move(filepath, destination_filepath)
                print(f"Moved {filepath} to {destination_filepath}")

    def download_unzip_keep_subset(self, 
                                   url: str, 
                                   zip_file_patterns: List[str], 
                                   dataset_name: str) -> None:
        """
        Downloads a ZIP file from the given URL, unpacks it into a temporary directory, 
        and moves only a subset of files (matching the given patterns) into a final directory.

        :param url: The URL of the ZIP file to download.
        :param zip_file_patterns: A list of glob patterns for files to retain.
        :param dataset_name: The name of the dataset (used for directory naming).
        """
        unzip_path = os.path.join(self.download_path, dataset_name)
        if os.path.exists(unzip_path):
            print(f"Skipping {dataset_name} as unzip path exists: {unzip_path}")
        else:
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_file_path = os.path.join(temp_dir, f"{dataset_name}.zip")
                print(f'Downloading to {zip_file_path}')
                self._download(url, zip_file_path)

                extract_path = os.path.join(temp_dir, dataset_name)
                self.unzip(zip_file_path, extract_path, extract_path)

                # Only keep a subset of the files to limit the storage used
                self.move_files(zip_file_patterns, extract_path, unzip_path)
        # Outside the block, the temporary directory and its contents will be automatically deleted
