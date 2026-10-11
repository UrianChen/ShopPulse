from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

ORDER_FIELDS = {
    "order_id": ["订单编号", "订单号"],
    "order_line_id": ["明细编号", "子订单号"],
    "sku": ["商品编码", "SKU"],
    "product_name": ["商品名称"],
    "paid_at": ["付款时间", "支付时间"],
    "quantity": ["购买数量", "数量"],
    "line_paid_minor": ["line_paid", "商品实付"],
    "line_refund_minor": ["line_refund", "累计商品退款"],
    "restocked_quantity": ["已回库件数"],
    "payment_state": ["支付状态", "订单状态"],
    "currency": ["币种"],
    "allocation_weight": ["优惠前金额", "分摊权重"],
    "shipping_minor": ["运费"],
    "unit_price": ["商品单价"],
    "discount_minor": ["商品优惠"],
}
COST_FIELDS = {
    "sku": ["商品编码"],
    "unit_cost": ["单位成本"],
    "currency": ["币种"],
    "effective_from": ["生效时间"],
    "effective_to": ["失效时间"],
}


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Shanghai"
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    currency_exponent: int = Field(default=2, ge=0, le=4)
    input_money_unit: Literal["major", "minor"] = "major"
    decimal_separator: Literal[".", ","] = "."
    amount_scope: Literal[
        "line_goods_excluding_shipping", "order_goods", "order_with_shipping", "derived"
    ] = "line_goods_excluding_shipping"
    payment_state_mode: Literal["mapped", "confirmed_all_paid"] = "mapped"
    status_mapping: dict[str, Literal["paid", "unpaid", "cancelled_unpaid"]] = Field(
        default_factory=dict
    )
    refund_mode: Literal["provided", "unknown", "confirmed_none"] = "unknown"
    refund_scope: Literal["line", "order"] = "line"
    coverage_start: str = ""
    coverage_end_exclusive: str = ""
    source_as_of: str = ""
    cost_effective_from: str = ""
    cost_effective_to: str = ""
    semantics_confirmed: bool = False
    coverage_confirmed: bool = False

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("Unknown IANA timezone") from None
        return value


class ImportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet_name: str | None = None
    header_row: int = Field(default=1, ge=1, le=100)
    encoding: Literal["utf-8-sig", "gb18030"] = "utf-8-sig"
    delimiter: Literal[",", ";", "\t"] = ","
    columns: dict[str, str] = Field(default_factory=dict)
    cost_version_id: UUID | None = None
    options: Options = Field(default_factory=Options)

    @field_validator("columns")
    @classmethod
    def valid_fields(cls, value):
        if set(value) - (set(ORDER_FIELDS) | set(COST_FIELDS)):
            raise ValueError("Unknown standard field")
        if len(value) != len(set(value.values())):
            raise ValueError("Each source column may be mapped once")
        return value


class MappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    config: ImportConfig


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int


class ResolutionRequest(RevisionRequest):
    excluded_rows: list[int] = Field(default_factory=list, max_length=100000)
    acknowledged_codes: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
