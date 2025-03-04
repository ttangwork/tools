import json
import os
import sys
import requests
import time
from pathlib import Path
import sqlite3
import configparser

def get_firefox_profiles_path():
    """Get the Firefox profiles directory path based on the operating system."""
    if sys.platform.startswith('win'):
        return os.path.join(os.environ['APPDATA'], 'Mozilla', 'Firefox', 'Profiles')
    elif sys.platform.startswith('darwin'):  # macOS
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Firefox', 'Profiles')
    else:  # Linux and others
        return os.path.join(os.path.expanduser('~'), '.mozilla', 'firefox')

def get_firefox_profiles():
    """Get a list of Firefox profiles."""
    profiles_path = get_firefox_profiles_path()
    if not os.path.exists(profiles_path):
        print(f"Firefox profiles directory not found: {profiles_path}")
        return []
    
    profiles = []
    # Check for profiles.ini file
    ini_path = os.path.join(os.path.dirname(profiles_path), 'profiles.ini')
    if os.path.exists(ini_path):
        config = configparser.ConfigParser()
        config.read(ini_path)
        for section in config.sections():
            if section.startswith('Profile'):
                if config.has_option(section, 'Path'):
                    profile_path = config.get(section, 'Path')
                    if not os.path.isabs(profile_path):
                        profile_path = os.path.join(os.path.dirname(profiles_path), profile_path)
                    profile_name = config.get(section, 'Name', fallback=profile_path)
                    profiles.append((profile_name, profile_path))
    
    # If no profiles found in profiles.ini, look for directories in profiles folder
    if not profiles:
        for item in os.listdir(profiles_path):
            full_path = os.path.join(profiles_path, item)
            if os.path.isdir(full_path) and (item.endswith('.default') or '.default' in item):
                profiles.append((item, full_path))
    
    return profiles

def extract_bookmarks_from_places_db(profile_path):
    """Extract bookmarks from places.sqlite database."""
    places_db = os.path.join(profile_path, 'places.sqlite')
    if not os.path.exists(places_db):
        print(f"places.sqlite not found in profile: {profile_path}")
        return []
    
    try:
        # Create a temporary copy of the database to avoid locking issues
        temp_db = os.path.join(os.path.dirname(places_db), 'temp_places.sqlite')
        import shutil
        shutil.copy2(places_db, temp_db)
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        # Query to get bookmarks with their URLs, titles and IDs
        query = """
        SELECT b.title, p.url, b.id, p.id
        FROM moz_bookmarks b
        JOIN moz_places p ON b.fk = p.id
        WHERE b.type = 1 AND p.url LIKE 'http%'
        """
        
        cursor.execute(query)
        bookmarks = [(title or "Untitled", url, bookmark_id, place_id) for title, url, bookmark_id, place_id in cursor.fetchall()]
        
        conn.close()
        os.remove(temp_db)
        
        return bookmarks
    except Exception as e:
        print(f"Error extracting bookmarks: {e}")
        return []

def extract_bookmarks_from_jsonlz4(profile_path):
    """Extract bookmarks from bookmarks.jsonlz4 file if available."""
    try:
        import lz4.block
        
        bookmarks_path = os.path.join(profile_path, 'bookmarkbackups')
        if not os.path.exists(bookmarks_path):
            return []
        
        # Get the latest backup file
        backup_files = [f for f in os.listdir(bookmarks_path) if f.endswith('.jsonlz4')]
        if not backup_files:
            return []
        
        # Sort by modification time, newest first
        backup_files.sort(key=lambda x: os.path.getmtime(os.path.join(bookmarks_path, x)), reverse=True)
        latest_backup = os.path.join(bookmarks_path, backup_files[0])
        
        # Read the compressed file
        with open(latest_backup, 'rb') as f:
            # Skip the Mozilla-specific header (8 bytes)
            f.seek(8)
            compressed_data = f.read()
            
        # Decompress
        decompressed_data = lz4.block.decompress(compressed_data)
        bookmark_json = json.loads(decompressed_data)
        
        # Extract bookmarks recursively
        bookmarks = []
        
        def extract_urls(node):
            if 'children' in node:
                for child in node['children']:
                    extract_urls(child)
            elif 'uri' in node and node.get('uri', '').startswith('http'):
                title = node.get('title', 'Untitled')
                bookmarks.append((title, node['uri'], None, None))  # No IDs for jsonlz4 bookmarks
        
        if bookmark_json:
            extract_urls(bookmark_json)
        return bookmarks
    
    except ImportError:
        print("lz4 module not found. Install with: pip install lz4")
        return []
    except Exception as e:
        print(f"Error extracting bookmarks from jsonlz4: {e}")
        return []

def validate_url(url, timeout=10):
    """Validate URL and return HTTP status code."""
    if not url:
        print("Error: Empty URL found")
        return None
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.head(url, timeout=timeout, headers=headers, allow_redirects=True)
        
        # If HEAD request fails, try GET
        if response.status_code >= 400:
            response = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True, stream=True)
            # Close the connection immediately after getting status
            response.close()
            
        return response.status_code
    except requests.exceptions.RequestException as e:
        print(f"Error validating {url}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error validating {url}: {e}")
        return None

def remove_bookmarks(profile_path, bookmark_ids):
    """Remove bookmarks from Firefox places.sqlite database."""
    if not bookmark_ids:
        return False
    
    places_db = os.path.join(profile_path, 'places.sqlite')
    if not os.path.exists(places_db):
        print(f"places.sqlite not found in profile: {profile_path}")
        return False
    
    # Check if Firefox is running
    if is_firefox_running():
        print("Warning: Firefox is running. Please close Firefox before deleting bookmarks.")
        return False
    
    try:
        # Make a backup of the database
        backup_db = places_db + '.backup'
        import shutil
        shutil.copy2(places_db, backup_db)
        print(f"Created backup of places.sqlite at: {backup_db}")
        
        # Connect to the actual database (not a temp copy)
        conn = sqlite3.connect(places_db)
        cursor = conn.cursor()
        
        # Begin transaction
        cursor.execute('BEGIN TRANSACTION')
        
        # Delete bookmarks
        deleted_count = 0
        for bookmark_id, place_id in bookmark_ids:
            if bookmark_id is None:
                print("Warning: Cannot delete bookmark without ID")
                continue
            
            try:
                # Delete from moz_bookmarks
                cursor.execute('DELETE FROM moz_bookmarks WHERE id = ?', (bookmark_id,))
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting bookmark {bookmark_id}: {e}")
        
        # Commit changes
        conn.commit()
        conn.close()
        
        print(f"Successfully deleted {deleted_count} bookmarks")
        return True
    except Exception as e:
        print(f"Error removing bookmarks: {e}")
        return False

def is_firefox_running():
    """Check if Firefox is currently running."""
    import platform
    import subprocess
    
    system = platform.system()
    try:
        if system == 'Windows':
            output = subprocess.check_output('tasklist', shell=True).decode()
            return 'firefox.exe' in output.lower()
        elif system == 'Darwin':  # macOS
            output = subprocess.check_output('ps -ax', shell=True).decode()
            return 'firefox' in output.lower()
        else:  # Linux
            output = subprocess.check_output('ps -A', shell=True).decode()
            return 'firefox' in output.lower()
    except Exception:
        # If we can't determine, assume it's running to be safe
        return True

def remove_bookmark_instructions():
    """Provide instructions for removing bookmarks."""
    print("\nTo remove bookmarks in Firefox:")
    print("1. Open Firefox")
    print("2. Press Ctrl+Shift+B (or Cmd+Shift+B on Mac) to open the Library window")
    print("3. Find and right-click on each bookmark you want to delete")
    print("4. Select 'Delete' from the context menu")
    print("5. Confirm the deletion if prompted")

def main():
    print("Firefox Bookmark Validator and Cleaner")
    print("=====================================")
    
    # Get Firefox profiles
    profiles = get_firefox_profiles()
    
    if not profiles:
        print("No Firefox profiles found. Please check if Firefox is installed correctly.")
        return
    
    # Let user select a profile
    print("\nAvailable Firefox profiles:")
    for i, (name, path) in enumerate(profiles):
        print(f"{i+1}. {name}")
    
    try:
        choice = int(input("\nSelect a profile (number): ")) - 1
        if choice < 0 or choice >= len(profiles):
            print("Invalid choice. Please enter a number between 1 and", len(profiles))
            return
        
        profile_name, profile_path = profiles[choice]
        print(f"\nUsing profile: {profile_name}")
        
        # Extract bookmarks
        print("Attempting to extract bookmarks from places.sqlite...")
        bookmarks = extract_bookmarks_from_places_db(profile_path)
        using_places_db = True
        
        if not bookmarks:
            # Try the backup method if places.sqlite didn't work
            print("No bookmarks found in places.sqlite. Trying backup method...")
            bookmarks = extract_bookmarks_from_jsonlz4(profile_path)
            using_places_db = False
        
        if not bookmarks:
            print("No bookmarks found or unable to read bookmarks.")
            return
        
        print(f"\nFound {len(bookmarks)} bookmarks. Starting validation...\n")
        
        # Collect all invalid bookmarks instead of prompting for each one
        invalid_bookmarks = []
        processed_count = 0
        
        # Validate each bookmark
        for i, bookmark_tuple in enumerate(bookmarks):
            try:
                # Ensure we have a proper tuple with necessary elements
                if not bookmark_tuple or len(bookmark_tuple) < 2:
                    print(f"[{i+1}/{len(bookmarks)}] Invalid bookmark entry: {bookmark_tuple}")
                    continue
                
                title, url = bookmark_tuple[0], bookmark_tuple[1]
                bookmark_id = bookmark_tuple[2] if len(bookmark_tuple) > 2 else None
                place_id = bookmark_tuple[3] if len(bookmark_tuple) > 3 else None
                
                # Make sure title and URL are not None
                title = title or "Untitled"
                
                if not url:
                    print(f"[{i+1}/{len(bookmarks)}] Empty URL for bookmark: {title[:50]}")
                    continue
                
                # Show progress
                progress = (i + 1) / len(bookmarks) * 100
                print(f"[{i+1}/{len(bookmarks)}] ({progress:.1f}%) Checking: {title[:50]}... ", end='', flush=True)
                
                status_code = validate_url(url)
                
                if status_code == 200:
                    print(f"OK (200)")
                else:
                    print(f"FAILED ({status_code if status_code else 'Error'})")
                    invalid_bookmarks.append((title, url, bookmark_id, place_id, status_code))
                
                processed_count += 1
                
                # Add a small delay to avoid overwhelming servers
                time.sleep(0.5)
            except Exception as e:
                print(f"Error processing bookmark {i+1}: {e}")
                continue
        
        # Display summary and all invalid bookmarks at the end
        print(f"\nValidation complete. Processed {processed_count} bookmarks.")
        
        if invalid_bookmarks:
            print(f"\nFound {len(invalid_bookmarks)} invalid bookmarks:")
            print("=" * 80)
            
            for i, (title, url, bookmark_id, place_id, status_code) in enumerate(invalid_bookmarks):
                print(f"{i+1}. Title: {title}")
                print(f"   URL: {url}")
                print(f"   Status: {status_code if status_code else 'Error'}")
                print(f"   ID: {bookmark_id}")
                print("-" * 80)
            
            # Ask if user wants to remove all or some bookmarks
            print("\nOptions:")
            print("1. Delete all invalid bookmarks (requires Firefox to be closed)")
            print("2. Delete specific invalid bookmarks (requires Firefox to be closed)")
            print("3. Get instructions to remove bookmarks manually")
            print("4. Export list of invalid bookmarks to a file")
            print("5. Exit without further action")
            
            try:
                action = int(input("\nWhat would you like to do? (1-5): "))
                
                if action == 1 or action == 2:
                    if not using_places_db:
                        print("Sorry, automatic deletion is only available when bookmarks are extracted from places.sqlite.")
                        print("Your bookmarks were extracted from a backup file.")
                        remove_bookmark_instructions()
                    else:
                        if is_firefox_running():
                            print("Please close Firefox before proceeding with deletion.")
                            input("Press Enter when Firefox is closed to continue...")
                        
                        if action == 1:
                            # Delete all invalid bookmarks
                            bookmark_ids_to_delete = [(b[2], b[3]) for b in invalid_bookmarks if b[2] is not None]
                            if bookmark_ids_to_delete:
                                if remove_bookmarks(profile_path, bookmark_ids_to_delete):
                                    print("Successfully deleted all invalid bookmarks.")
                                else:
                                    print("Failed to delete some or all bookmarks.")
                            else:
                                print("No valid bookmark IDs found for deletion.")
                        
                        elif action == 2:
                            # Let user select specific bookmarks to delete
                            print("\nEnter the numbers of bookmarks to delete (comma-separated, e.g., 1,3,5)")
                            selection = input("Bookmarks to delete: ")
                            try:
                                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                                bookmark_ids_to_delete = []
                                
                                for idx in indices:
                                    if 0 <= idx < len(invalid_bookmarks) and invalid_bookmarks[idx][2] is not None:
                                        bookmark_ids_to_delete.append((invalid_bookmarks[idx][2], invalid_bookmarks[idx][3]))
                                    else:
                                        print(f"Invalid selection: {idx+1}")
                                
                                if bookmark_ids_to_delete:
                                    if remove_bookmarks(profile_path, bookmark_ids_to_delete):
                                        print(f"Successfully deleted {len(bookmark_ids_to_delete)} bookmarks.")
                                    else:
                                        print("Failed to delete some or all bookmarks.")
                                else:
                                    print("No valid bookmark IDs selected for deletion.")
                            except ValueError:
                                print("Invalid input format. Please use comma-separated numbers.")
                
                elif action == 3:
                    remove_bookmark_instructions()
                
                elif action == 4:
                    filename = input("Enter filename to save results (default: invalid_bookmarks.txt): ") or "invalid_bookmarks.txt"
                    with open(filename, "w") as f:
                        f.write(f"Invalid Firefox Bookmarks - {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        for i, (title, url, bookmark_id, place_id, status_code) in enumerate(invalid_bookmarks):
                            f.write(f"{i+1}. Title: {title}\n")
                            f.write(f"   URL: {url}\n")
                            f.write(f"   Status: {status_code if status_code else 'Error'}\n")
                            f.write("-" * 50 + "\n")
                    print(f"Results saved to {filename}")
            except ValueError:
                print("Invalid input. Exiting.")
        else:
            print("All bookmarks are valid! No issues found.")
        
    except KeyboardInterrupt:
        print("\nOperation canceled by user.")
    except ValueError:
        print("\nInvalid input. Please enter a number.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()