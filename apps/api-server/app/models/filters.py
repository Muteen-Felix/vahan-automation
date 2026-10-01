from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VahanFilters(BaseModel):
    """Filter payload accepted from the Web UI.

    Unknown fields are retained so the MVP does not need a backend release each
    time VAHAN adds a filter. The extension remains the source of truth for the
    selectors and supported values.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    states: list[str] = Field(default_factory=list)
    rtos: list[str] = Field(default_factory=list)
    category_groups: list[str] = Field(default_factory=list, alias="categoryGroups")
    fuels: list[str] = Field(default_factory=list)
    y_axis: str | None = Field(default=None, alias="yAxis")
    x_axis: str | None = Field(default=None, alias="xAxis")
    auto_apply: bool = Field(default=False, alias="autoApply")
    auto_export: bool = Field(default=True, alias="autoExport")

    def extension_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)
