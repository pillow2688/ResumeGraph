export interface Admin {
  id: string;
  username: string;
}

export interface AdminLoginRequest {
  username: string;
  password: string;
}

export interface AdminLoginResponse {
  admin: Admin;
}

