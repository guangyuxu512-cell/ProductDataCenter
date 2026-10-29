from app.core.exceptions.errors import AppError


class ProductRequestError(AppError):
    code = "PRODUCT_REQUEST_INVALID"
    status_code = 400


class ProductNotFound(AppError):
    code = "PRODUCT_NOT_FOUND"
    message = "商品不存在"
    status_code = 404


class GroupNotFound(AppError):
    code = "PRODUCT_GROUP_NOT_FOUND"
    message = "商品分组不存在"
    status_code = 404


class GroupNameConflict(AppError):
    code = "PRODUCT_GROUP_NAME_CONFLICT"
    message = "分组名称已存在"
    status_code = 409


class ExportUnavailable(AppError):
    code = "PRODUCT_EXPORT_UNAVAILABLE"
    status_code = 409
