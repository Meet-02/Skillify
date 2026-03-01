from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

def hash_password(password: str):
    # bcrypt limit fix
    password = password[:72]
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str):
    password = password[:72]
    return pwd_context.verify(password, hashed)