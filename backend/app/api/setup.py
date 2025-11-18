"""
Setup wizard API endpoints
Handles initial configuration for first-time users
"""

import logging
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..config import get_settings, Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    """Setup status response"""
    setup_required: bool
    reason: Optional[str] = None


class DataAccessDetection(BaseModel):
    """Detected data access options"""
    volume_available: bool
    volume_path: Optional[str] = None
    taf_files_found: int = 0
    tonies_found: int = 0
    image_paths: List[str] = []


class TeddyCloudTest(BaseModel):
    """TeddyCloud connection test request"""
    url: str


class TeddyCloudTestResult(BaseModel):
    """TeddyCloud connection test result"""
    success: bool
    error: Optional[str] = None
    version: Optional[str] = None
    boxes: List[Dict[str, Any]] = []


class SetupConfiguration(BaseModel):
    """Complete setup configuration"""
    # TeddyCloud
    teddycloud_url: str
    
    # Image paths
    custom_img_path: str
    custom_img_json_path: str
    use_smb: bool = False
    # Preferences
    ui_language: str = "en"
    default_language: str = "de-de"
    auto_parse_taf: bool = True
    selected_box: Optional[str] = None


@router.get("/status", response_model=SetupStatus)
async def check_setup_status(settings: Settings = Depends(get_settings)):
    """
    Check if initial setup is required
    
    Returns:
        SetupStatus with setup_required flag
    """
    try:
        config_file = Path("/config/config.yaml")

        # Check if config.yaml exists and is configured
        if not config_file.exists():
            return SetupStatus(
                setup_required=True,
                reason="Configuration file not found"
            )
        
        # Check if TeddyCloud URL is still default
        if settings.teddycloud.url == "http://docker":
            # Check if we can actually connect
            import httpx
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(f"{settings.teddycloud.url}/api/toniesCustomJson")
                    if response.status_code != 200:
                        return SetupStatus(
                            setup_required=True,
                            reason="TeddyCloud connection not configured"
                        )
            except:
                return SetupStatus(
                    setup_required=True,
                    reason="Cannot connect to TeddyCloud"
                )
        
        # Setup completed
        return SetupStatus(setup_required=False)
        
    except Exception as e:
        logger.error(f"Error checking setup status: {e}")
        return SetupStatus(
            setup_required=True,
            reason=str(e)
        )


@router.get("/detect", response_model=DataAccessDetection)
async def detect_data_access():
    """
    Auto-detect available data access methods
    
    Returns:
        Detected volume paths and file counts
    """
    try:
        result = DataAccessDetection(volume_available=False)
        
        # Check if /data volume is mounted and has TeddyCloud data
        data_path = Path("/data")
        if data_path.exists() and data_path.is_dir():
            # Check for TeddyCloud structure
            config_path = data_path / "config"
            library_path = data_path / "library"
            
            if config_path.exists() and library_path.exists():
                result.volume_available = True
                result.volume_path = "/data"
                
                # Count TAF files
                try:
                    taf_files = list(library_path.rglob("*.taf"))
                    result.taf_files_found = len(taf_files)
                except:
                    pass
                
                # Count tonies
                try:
                    tonies_file = config_path / "tonies.custom.json"
                    if tonies_file.exists():
                        import json
                        with open(tonies_file) as f:
                            tonies = json.load(f)
                            result.tonies_found = len(tonies) if isinstance(tonies, list) else 0
                except:
                    pass
                
                # Detect image directories
                image_dirs = []
                if (library_path / "own" / "pics").exists():
                    image_dirs.append("/data/library/own/pics")
                if (data_path / "www" / "custom_img").exists():
                    image_dirs.append("/data/www/custom_img")
                result.image_paths = image_dirs
        
        return result
        
    except Exception as e:
        logger.error(f"Error detecting data access: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-teddycloud", response_model=TeddyCloudTestResult)
async def test_teddycloud_connection(test: TeddyCloudTest):
    """
    Test connection to TeddyCloud API
    
    Args:
        test: TeddyCloud connection details
        
    Returns:
        Test result with boxes if successful
    """
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=10) as client:
            # Test toniesCustomJson endpoint
            response = await client.get(f"{test.url}/api/toniesCustomJson")
            
            if response.status_code != 200:
                return TeddyCloudTestResult(
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text[:100]}"
                )
            
            # Try to get boxes
            boxes = []
            try:
                boxes_response = await client.get(f"{test.url}/api/tonieboxes")
                if boxes_response.status_code == 200:
                    boxes_data = boxes_response.json()
                    if isinstance(boxes_data, list):
                        boxes = [{"id": b.get("id"), "name": b.get("name", "Unknown")} 
                                for b in boxes_data]
            except:
                pass
            
            return TeddyCloudTestResult(
                success=True,
                boxes=boxes
            )
            
    except Exception as e:
        logger.error(f"TeddyCloud connection test failed: {e}")
        return TeddyCloudTestResult(
            success=False,
            error=str(e)
        )


@router.post("/save")
async def save_configuration(config: SetupConfiguration):
    """
    Save setup configuration to config.yaml
    
    Args:
        config: Complete setup configuration
        
    Returns:
        Success status
    """
    try:
        # Build config structure
        config_data = {
            "teddycloud": {
                "url": config.teddycloud_url,
                "api_base": "/api",
                "timeout": 30
            },
            "volumes": {
                "enabled": not config.use_smb,
                "config_path": "/data/config",
                "custom_img_path": config.custom_img_path,
                "custom_img_json_path": config.custom_img_json_path,
                "library_path": "/data/library"
            },
            "app": {
                "auto_parse_taf": config.auto_parse_taf,
                "confirm_before_save": True,
                "auto_reload_config": True,
                "default_language": config.default_language,
                "max_image_size_mb": 5,
                "allowed_image_formats": ["jpg", "jpeg", "png", "webp"],
                "show_hidden_files": False,
                "recursive_scan": True
            },
            "advanced": {
                "parse_cover_from_taf": True,
                "extract_track_names": True,
                "log_level": "INFO",
                "cache_taf_metadata": True,
                "cache_ttl_seconds": 300
            }
        }
        
        # Add selected box if provided
        if config.selected_box:
            config_data["app"]["selected_box"] = config.selected_box
        
        # Write to config.yaml in persistent volume
        config_file = Path("/config/config.yaml")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        
        logger.info("Setup configuration saved successfully")
        
        return {
            "success": True,
            "message": "Configuration saved. Please restart the application."
        }
        
    except Exception as e:
        logger.error(f"Failed to save configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))
