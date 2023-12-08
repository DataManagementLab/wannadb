# Routes _wannadbBackend_

The flask app is running by default on port 8000. Here we assume that the app is running on localhost.

---

-   [HelloWorld](#helloworld)
-   [Register](#register)
-   [Login](#login)

---

## HelloWorld

**GET**

Say hello to the world.

```
http://localhost:8000/
```

---

## Register

**POST**

Register a new user.

```
http://localhost:8000/register
```

### Body

```json
{
    "username": "username",
    "password": "password"
}
```

### Response

-   200: User register **failed**:
    ```json
    {
        "message": "User register failed",
        "status": false
    }
    ```
-   200: User register **success**:
    ```json
    {
        "message": "User registered successfully",
        "status": true,
        "token": "eyJhbGciOiJIUI1NiIsIn5cCI6IkpXVCJ9.ey1c2VyIjocGhpbEiLCJpZCIM30.v_lKLd0X-PABkRFXHZa..."
    }
    ```

---

## Login

**GET,POST**

Login as user

```
http://localhost:8000/login
```

### Body

```json
{
    "username": "username",
    "password": "password"
}
```

### Response

-   200: User login **failed**:
    ```json
    {
        "message": "Wrong Password",
        "status": false
    }
    ```
-   200: User login **success**:
    ```json
    {
        "message": "Log in successfully",
        "status": true,
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1..."
    }
    ```

---
