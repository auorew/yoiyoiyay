"""Settings module"""

import os

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import AnyUrl, BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# current timestamp & app directory
DATE_RUN = datetime.now()
WORK_DIR = Path(os.getcwd())


class BotSettings(BaseSettings):
    ##### main #####

    # telegram tokens
    api_id: int = Field(0)
    api_hash: str = Field("")
    token: str = Field("")

    # postesql database URL
    database_url: str = Field("sqlite:///./db.sqlite3")

    # twitter [auth_token] (needed for gallery-dl's twitter API)
    tw_token: Optional[str] = Field("")

    # twitter [ct0] (needed for gallery-dl's twitter API)
    tw_cookie: Optional[str] = Field("")

    # twitter [username] (needed for gallery-dl's twitter API)
    tw_user: Optional[str] = Field("")

    # twitter [password] (needed for gallery-dl's twitter API)
    tw_pass: Optional[str] = Field("")

    # deprecated! instagram [sessionid] (needed for gallery-dl's instagram API)
    ig_token: Optional[str] = Field("")

    # youtube cookies (needed for yt-dlp's youtube API)
    yt_cookies: Optional[str] = Field("")

    # youtube cookies key (see above)
    yt_key: Optional[str] = Field("")

    # pixiv refresh token (needed for pixiv API)
    px_refresh: Optional[str] = Field("")

    # telegram channel id [in the form -100XXXXXXXXXX] used as a dump for inline mode
    dump: int = Field(0)

    ##### webserver #####

    api_key: str = Field("0" * 32, min_length=32)

    ##### webhook #####

    # host name
    hook_url: Optional[str] = Field("")

    # port
    port: int = Field(8443)

    ##### bot files #####

    # cache directory
    cache_dir: Path = Field(WORK_DIR / "cache")

    # help file
    help_file: Path = Field(WORK_DIR / "help.txt")

    # settings file
    log_settings_file: Path = Field(WORK_DIR / "settings.toml")

    ##### optional #####

    # whether to use local image resizer (memory should not be limited)
    resizer_local: Optional[bool] = Field(True)

    # whether to use local converter (memory should not be limited)
    converter_local: Optional[bool] = Field(True)

    # image resizer API to send requests to, if memory is limited
    resizer_api: Optional[str] = Field("")

    # converter API to send requests to, if memory is limited
    converter_api: Optional[str] = Field("")

    # logtail token
    logtail_token: Optional[str] = Field("")

    # google cloud logging
    gd_log: Optional[str] = Field("")

    # health check URL
    health_check_url: Optional[AnyUrl] = Field(None)

    # your proxy URL
    proxy_url: Optional[AnyUrl] = Field(None)


bot_settings = BotSettings()


class FileLog(BaseModel):
    enable: bool = Field(False)
    date: str = Field("%Y-%m-%d.%H-%M-%S")
    path: Path = Field(WORK_DIR / "log")
    pref: str = Field("")


class BasicLog(BaseModel):
    level: str = Field("DEBUG")
    form: str = Field("%(asctime)s [%(levelname)s] > %(name)s: %(message)s")


class OutLog(BasicLog):
    file: Optional[BasicLog]


class ExcludeLog(BasicLog):
    name: str
    enable: bool = Field(False)
    level: str = Field("WARNING")


class LogSettings(BaseSettings):
    file: FileLog
    root: OutLog
    bot: OutLog
    tail: OutLog

    lib: list[ExcludeLog]

    model_config: SettingsConfigDict = SettingsConfigDict(
        toml_file=bot_settings.log_settings_file
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        **kwargs,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (TomlConfigSettingsSource(settings_cls),)


log_settings = LogSettings()
