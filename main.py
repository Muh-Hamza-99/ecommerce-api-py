from fastapi import FastAPI, Request, HTTPException, status, Depends, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import (OAuth2PasswordBearer, OAuth2PasswordRequestForm)
from fastapi.staticfiles import StaticFiles

from tortoise.contrib.fastapi import register_tortoise
from tortoise.signals import post_save
from tortoise import BaseDBAsyncClient

import jwt

from PIL import Image

from typing import List, Optional, Type
import secrets

from models import *
from auth import *
from email import (send_email)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
FILEPATH = "./static/images"

templates = Jinja2Templates(directory="templates")

oauth2_schema = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_schema)):
    try:
        payload = jwt.decode(
            token, config_credentials["SECRET"], algorithms=["HS256"])
        user = await User.get(id=payload.get("id"))
    except:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token / Expired token!",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return await user

@post_save(User)
async def create_business(sender: "Type[User]", instance: User, created: bool, using_db: "Optional[BaseDBAsyncClient]", update_fields: List[str]) -> None:
    if created:
        business_obj = await Business.create(business_name=instance.username, owner=instance)
        await business_pydantic.from_tortoise_orm(business_obj)
        await send_email([instance.email], instance)

@app.post("/token")
async def generate_token(request_form: OAuth2PasswordRequestForm = Depends()):
    token = await token_generator(request_form.username, request_form.password)
    return {"status": "success", "access_token": token, "token_type": "Bearer"}

@app.post("/register")
async def user_registeration(user: user_pydanticIn):
    user_info = user.dict(exclude_unset=True)
    user_info["password"] = hash_password(user_info["password"])
    user_obj = await User.create(**user_info)
    new_user = await user_pydantic.from_tortoise_orm(user_obj)
    return {"status": "success", "data": f"Hello {new_user.username}. Thanks for using my API! Check your email inbox to verify your email to confirm registration!"}

@app.get("/verify", response_class=HTMLResponse)
async def email_verification(request: Request, token: str):
    user = await verify_token(token)
    if user and not user.is_verified:
        user.is_verified = True
        await user.save()
        return templates.TemplateResponse("verify.html", {"request": request, "username": user.username})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token / Expired token!",
        headers={"WWW-Authenticate": "Bearer"}
    )

@app.post("/user/me")
async def user_login(user: user_pydanticIn = Depends(get_current_user)):
    business = await Business.get(owner=user)
    logo = business.logo
    logo_path = f"localhost:8000/static/images/{logo}"
    return {"status": "success", "data": {"username": user.username, "email": user.email, "verified": user.is_verified, "join_date": user.join_date.strftime("%b %d %Y"), logo: logo_path}}

@app.post("/uploadfile/profile")
async def create_upload_file(file: UploadFile = File(...), user: user_pydantic = Depends(get_current_user)):
    filename = file.filename
    extension = filename.split(".")[1]
    if extension not in ["png", "jpg", "jpeg"]:
        return {"status": "error", "message": "Invalid file extension!"}
    token_name = f"{secrets.token_hex(10)}.{extension}"
    generated_name = FILEPATH + token_name
    file_content = await file.read()
    with open(generated_name, "wb") as file:
        file.write(file_content)
    img = Image.open(generated_name)
    img = img.resize(size=(200, 200))
    img.save(generated_name)
    file.close()
    business = await Business.get(owner=user)
    owner = await business.owner
    if owner == user:
        business.logo = token_name
        await business.save()
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action!",
            headers={"WWW-Authenticate": "Bearer"}
        )
    file_url = f"localhost:8000{generated_name[1:]}"
    return {"status": "success", "filename": file_url}

@app.post("/uploadfile/product/{id}")
async def create_upload_file(id: int, file: UploadFile = File(...), user: user_pydantic = Depends(get_current_user)):
    filename = file.filename
    extension = filename.split(".")[1]
    if extension not in ["png", "jpg", "jpeg"]:
        return {"status": "error", "message": "Invalid file extension!"}
    token_name = f"{secrets.token_hex(10)}.{extension}"
    generated_name = FILEPATH + token_name
    file_content = await file.read()
    with open(generated_name, "wb") as file:
        file.write(file_content)
    img = Image.open(generated_name)
    img = img.resize(size=(200, 200))
    img.save(generated_name)
    file.close()
    product = await Product.get(id=id)
    business = await product.business
    owner = await business.owner
    if owner == user:
        product.product_image = token_name
        await product.save()
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action!",
            headers={"WWW-Authenticate": "Bearer"}
        )
    file_url = f"localhost:8000{generated_name[1:]}"
    return {"status": "success", "filename": file_url}

@app.get("/products")
async def get_products():
    response = await product_pydantic.from_queryset(Product.all())
    return {status: "success", "data": response}

@app.post("/products")
async def add_product(product: product_pydanticIn, user: user_pydantic = Depends(get_current_user)):
    product = product.dict(exclude_unset=True)
    if product["original_price"] > 0:
        product["percentage_discount"] = (
            (product["original_price"] - product["new_price"]) / product["original_price"]) * 100
        product_obj = await Product.create(**product, business=user)
        product_obj = await product_pydantic.from_tortoise_orm(product_obj)
        return {"status": "success", "data": product_obj}
    else:
        return {"status": "error", "message": "Invalid data sent to the API!"}

@app.get("/products/{id}")
async def get_product(id: int):
    product = await Product.get(id=id)
    business = await product.business
    owner = await business.owner
    response = await product_pydantic.from_queryset_single(Product.get(id=id))
    return {status: "success", "data": {"product_details": response, "business_details": {"name": business.business_name, "city": business.city, "region": business.region, "description": business.business_description, "business_id": business.id, "logo": business.logo, "owner_id": owner.id, "email": owner.email, "join_date": owner.join_date.strftime("%b %d %Y")}}}

@app.put("/products/{id}")
async def update_product(id: int, update_info: product_pydanticIn, user: user_pydantic = Depends(get_current_user)):
    product = await Product.get(id=id)
    business = await product.business
    owner = await business.owner
    update_info == update_info.dict(exclude_unset=True)
    update_info["date_published"] = datetime.utcnow()
    if user == owner and update_info["original_price"] > 0:
        update_info["percentage_discount"] = (
            (product["original_price"] - product["new_price"]) / product["original_price"]) * 100
        product = await product.update_from_dict(update_info)
        product.save()
        response = await product_pydantic.from_tortoise_orm(product)
        return {"status": "success", "data": response}
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action / Invalid data sent to API!",
            headers={"WWW-Authenticate": "Bearer"}
        )

@app.delete("/products/{id}")
async def delete_product(id: int, user: user_pydantic = Depends(get_current_user)):
    product = await Product.get(id=id)
    business = await product.business
    owner = await business.owner
    if user == owner:
        product.delete()
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action!",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"status": "success"}

@app.put("/business/{id}")
async def update_business(id: int, update_business: business_pydanticIn, user: user_pydantic = Depends(get_current_user)):
    update_business = update_business.dict()
    business = await Business.get(id=id)
    business_owner = await business.owner
    if user == business_owner:
        await business.update_from_dict(update_business)
        business.save()
        response = await business_pydantic.from_tortoise_orm(business)
        return {"status": "success", "data": response}
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated to perform this action!",
            headers={"WWW-Authenticate": "Bearer"},
        )

register_tortoise(app, db_url="sqlite://datebase.sqlite3", modules={"models": [
                  "models"]}, generate_schemas=True, add_exception_handlers=True)
