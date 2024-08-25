# Routes _WannaDBBackend_

## Introduction

Welcome to the documentation for our application! In this guide, you will find detailed information about the various routes and endpoints available in our API.

Whether you are a user, a file manager, or a core functionality developer, this documentation will provide you with the necessary information to interact with our application effectively.

Please refer to the specific sections for [user routes](#user-routes), [file routes](#file-routes), and [core routes](#core-routes) to find the relevant endpoints and their corresponding request methods and bodies.

**Base URL:** `http://localhost:8000`

If you have any questions or need further assistance, feel free to reach out to us.

## Authentication

The authentication method used in this application is JSON Web Token (JWT). JWT is a widely used method for securely transmitting information between parties as a JSON object. It is commonly used for authentication and authorization purposes in web applications. With JWT, a token is generated and sent to the client upon successful authentication. This token is then included in subsequent requests to authenticate and authorize the user. The server can verify the authenticity and integrity of the token to ensure that the user is authenticated and authorized to access the requested resources.

To learn more about JWT and its implementation in this application, please refer to the application's documentation or codebase.

## Endpoints

### User Routes

This category of routes handles the requests related to user and organization management. These routes are responsible for user registration, login, and deletion functionality. Additionally they are responsible for organization creation, leaving and further management functionalities.

- [Register New User](#register-new-user)
- [Login as User](#login-as-user)
- [Delete User](#delete-user)
- [Create Organization](#create-organization)
- [Leave Organization](#leave-organization)
- [Get Organizations for User](#get-organizations-for-user)
- [Get Organization Name by ID](#get-organization-name-by-id)
- [Get Organization Names for User](#get-organization-names-for-user)
- [Add User to Organization](#add-user-to-organization)
- [Get Members of Organization](#get-members-of-organization)
- [Get User Name Suggestions](#get-user-name-suggestions)

---

#### Register New User

-   Method: `POST`
-   URL: `/register`
-   Body
    ```json
    {
        "username": "username",
        "password": "password"
    }
    ```
-   Response
    -   422 : User register **failed**:
        ```json
        {
            "message": "User register failed"
        }
        ```
    -   201: User register **success**:
        ```json
        {
            "message": "User registered successfully",
            "token": "eyJhbGciOiJIUI1NiIsIn5cCI6IkpXVCJ9.ey1c2VyIjocGhpbEiLCJpZCIM30.v_lKLd0X-PABkRFXHZa..."
        }
        ```

---

#### Login as User


-   Method: `POST`
-   URL: `/login`
-   Body
    ```json
    {
        "username": "username",
        "password": "password"
    }
    ```
-   Response
    -   401: User login **failed**:
        ```json
        {
            "message": "Wrong Password"
        }
        ```
    -   200: User login **success**:
        ```json
        {
            "message": "Log in successfully",
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1..."
        }
        ```

---

#### Delete User

```
/deleteUser/
```

-   Method: `POST`
-   URL: `/deleteUser/`
-   Body
    ```json
    {
        "username": "username",
        "password": "password"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   401: User not authorized.
    -   401: Wrong Password.
    -   204: User deleted successfully.
    -   409: User deletion failed.

---

#### Create Organization

-   Method: `POST`
-   URL: `/createOrganisation`
-   Body
    ```json
    {
        "organisationName": "organisation_name"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: Organization created successfully.
    -   409: Organization creation failed.

---

#### Leave Organization

-   Method: `POST`
-   URL: `/leaveOrganisation`
-   Body
    ```json
    {
        "organisationId": "organisation_id"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: User left the organization successfully.
    -   500: Error leaving organization.

---

#### Get Organizations for User

-   Method: `GET`
-   URL: `/getOrganisation`
-   Body
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: Retrieved user's organizations successfully.
        ```json
        {
            "organisation_ids": ["number"]
        }
        ```
    -   404: User is not in any organization.
    -   409: Error retrieving organizations.

---

#### Get Organization Name by ID

-   Method: `GET`
-   URL: `/getOrganisationName/<_id>`
-   Path Parameters
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Body
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: Retrieved organization name successfully.
        ```json
        {
            "organisation_name": ["string"]
        }
        ```
    -   404: Organization not found.
    -   409: Error retrieving organization name.

---

#### Get Organization Names for User

-   Method: `GET`
-   URL: `/getOrganisationNames`
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: Retrieved user's organization names successfully.
        ```json
        {
            "organisations": ["number"]
        }
        ```
    -   404: User is not in any organization.
    -   409: Error retrieving organization names.

---

#### Add User to Organization

-   Method: `POST`
-   URL: `/addUserToOrganisation`
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Body
    ```json
    {
        "organisationId": "organisation_id",
        "newUser": "new_user"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: User added to the organization successfully.
        ```json
        {
            "organisation_id": "number"
        }
        ```
    -   409: Error adding user to organization.

---

#### Get Members of Organization
```
/getOrganisationMembers/<_id>
```

-   Method: `GET`
-   URL
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Retrieved organization members successfully.
    ```json
    {
        "members": ["string"]
    }
    ```
-   404: Organization not found.
-   409: Error retrieving organization members.

---

#### Get User Name Suggestions

-   Method: `GET`
-   URL: `/get/user/suggestion/<_prefix>`
-   Path Parameters
    ```json
    {
        "_prefix": "organisation_id"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   400: Invalid authorization token.
    -   200: Retrieved username suggestions successfully.
        ```json
        {
            "usernames": ["string"]
        }
        ```

---

### File Routes

The File Routes category includes various endpoints for managing files within the application. These routes allow users to upload files, retrieve a list of files for a specific organization, get the document base for an organization, update the content of a file, and delete a file. These routes provide essential functionality for file management and enable users to interact with the application's file system effectively. By utilizing these routes, users can easily upload, retrieve, update, and delete files as needed for their organization's needs.

-   [Upload File](#upload-file)
-   [Get Files](#get-files)
-   [Get Document Base for Organization](#get-document-base-for-organization)
-   [Update File Content](#update-file-content)
-   [Delete File](#delete-file)
-   [Get File](#get-file)

---

#### Upload File

-   Method: `POST`
-   URL: `/data/upload/file`
-   Form
    -   `file`: The file to upload.
    -   `organisationId`: ID of the organization.
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   200: File uploaded successfully.
        ```json
        {
            "document_ids": ["number"]
        }
        ```
    -   400: Invalid file type.
        ```json
        {
            "document_ids": ["string"]
        }
        ```
    -   207: Multiple files uploaded, some with errors.
        ```json
        {
            "document_ids": ["number|string"]
        }
        ```

---

#### Get Files

-   Method: `GET`
-   URL: `/data/organization/get/files/<_id>`
-   Path Parameters
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   200: Retrieved organization files successfully.
        ```json
        {
            "documents": "id"
        }
        ```

---

#### Get Document Base for Organization

-   Method: `GET`
-   URL: `/data/organization/get/documentbase/<_id>`
-   Path Parameters
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   200: Retrieved document base successfully.
        ```json
        {
            "document_base": "document_base"
        }
        ```

---

#### Update File Content

-   Method: `POST`
-   URL: `/data/update/file/content`
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Body
    ```json
    {
        "documentId": "document_id",
        "newContent": "new_content"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   200: File content updated successfully.
        ```json
        {
            "status": "bool"
        }
        ```

---

#### Delete File

-   Method: `POST`
-   URL: `/data/file/delete`
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Body
    ```json
    {
        "documentId": "document_id"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   200: File deleted successfully.
        ```json
        {
            "status": "bool"
        }
        ```

---

#### Get File

-   Method: `GET`
-   URL: `/data/get/file/<_id>`
-   Path Parameters
    ```json
    {
        "_id": "document_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Response
    -   401: No authorization provided.
    -   200: Retrieved file successfully.
        ```json
        {
            "document_ids": ["list", "string", "bytes"]
        }
        ```
    -   404: File not found.
        ```json
        {
            "document_ids": []
        }
        ```
    -   206: Partial content retrieved.
        ```json
        {
            "document_ids": ["list", "string", "bytes"]
        }
        ```

--

### Core Routes

This module defines Flask routes for the 'core' functionality of the WannaDB UI. It handles document bases and nuggets, as those are the central components of WannaDB.

- [Create Document Base](#create-document-base)
- [Load Document Base](#load-document-base)
- [Interactive Document Population](#interactive-document-population)
- [Add Attributes to Document Base](#add-attributes-to-document-base)
- [Update Attributes of Document Base](#update-attributes-of-document-base)
- [Sort Nuggets](#sort-nuggets)
- [Confirm Custom Nugget](#confirm-custom-nugget)
- [Confirm Match Nugget](#confirm-match-nugget)
- [Get Document Base for Organization](#get-document-base-for-organization)
 

---

#### Create Document Base

-   Method: `POST`
-   URL: `/core/document_base`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `document_ids`: Comma-separated list of document IDs.
    -   `attributes`: Comma-separated list of attributes.
-   Response
    -   401: No authorization provided.
    -   200: Document base created successfully.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Load Document Base

-   Method: `POST`
-   URL: `/core/document_base/load`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
-   Response
    -   401: No authorization provided.
    -   200: Document base loaded successfully.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Interactive Document Population

-   Method: `POST`
-   URL: `/core/document_base/interactive`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
-   Response
    -   401: No authorization provided.
    -   200: Document base populated interactively.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Add Attributes to Document Base

-   Method: `POST`
-   URL: `/core/document_base/attributes/add`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `attributes`: Comma-separated list of attributes.
-   Response
    -   401: No authorization provided.
    -   200: Attributes added to document base successfully.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Update Attributes of Document Base

-   Method: `POST`
-   URL: `/core/document_base/attributes/update`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `attributes`: Comma-separated list of attributes.
-   Response
    -   401: No authorization provided.
    -   200: Attributes updated successfully.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Sort Nuggets

-   Method: `POST`
-   URL: `/core/document_base/order/nugget`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `documentName`: Your document name.
    -   `documentContent`: Your document content.
-   Response
    -   401: No authorization provided.
    -   200: Nuggets sorted successfully.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Confirm Custom Nugget

-   Method: `POST`
-   URL: `/core/document_base/confirm/nugget/custom`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `documentName`: Your document name.
    -   `documentContent`: Your document content.
    -   `nuggetText`: Nugget as text.
    -   `startIndex`: Start index of the nugget.
    -   `endIndex`: End index of the nugget.
    -   `interactiveCallTaskId`: Interactive call task ID.
-   Response
    -   401: No authorization provided.
    -   200: Nugget confirmed successfully.
        ```json
        {"task_id": "task_id"}
        ```

---

#### Confirm Match Nugget

-   Method: `POST`
-   URL: `/core/document_base/confirm/nugget/match`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `documentName`: Your document name.
    -   `documentContent`: Your document content.
    -   `nuggetText`: Nugget as text.
    -   `startIndex`: Start index of the nugget.
    -   `endIndex`: End index of the nugget.
    -   `interactiveCallTaskId`: Interactive call task ID.
-   Response
    -   401: No authorization provided.
    -   200: Nugget confirmed successfully.
        ```json
        {"task_id": "task_id"}
        ```

#### Confirm Multi Match

-   Method: `POST`
-   URL: `/core/document_base/confirm/nugget/multi_match`
-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `matches`: List of matches each containing:
        -   `documentName`: Your document name.
        -   `documentContent`: Your document content.
        -   `nuggetText`: Nugget as text.
        -   `startIndex`: Start index of the nugget.
        -   `endIndex`: End index of the nugget.
    -   `interactiveCallTaskId`: Interactive call task ID.
-   Response
    -   401: No authorization provided.
    -   200: Nugget confirmed successfully.
        ```json
        {"task_ids": ["task_id1", ...]}
        ```
