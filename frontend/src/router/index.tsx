import { Navigate, createBrowserRouter } from "react-router-dom";

import { AccessGrants } from "../pages/AccessGrants";
import { AdminLogin } from "../pages/AdminLogin";
import { DocumentDetail } from "../pages/DocumentDetail";
import { Portfolio } from "../pages/Portfolio";
import { ProjectDocuments } from "../pages/ProjectDocuments";
import { Projects } from "../pages/Projects";
import { RecruiterAccess } from "../pages/RecruiterAccess";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate replace to="/admin/login" />,
  },
  {
    path: "/admin/login",
    element: <AdminLogin />,
  },
  {
    path: "/admin/projects",
    element: <Projects />,
  },
  {
    path: "/admin/projects/:projectId/documents",
    element: <ProjectDocuments />,
  },
  {
    path: "/admin/documents/:documentId",
    element: <DocumentDetail />,
  },
  {
    path: "/admin/access-grants",
    element: <AccessGrants />,
  },
  {
    path: "/access",
    element: <RecruiterAccess />,
  },
  {
    path: "/portfolio",
    element: <Portfolio />,
  },
  {
    path: "*",
    element: <Navigate replace to="/admin/login" />,
  },
]);
