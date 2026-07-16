import { Navigate, createBrowserRouter } from "react-router-dom";

import { AccessGrants } from "../pages/AccessGrants";
import { AdminLogin } from "../pages/AdminLogin";
import { AdminUsers } from "../pages/AdminUsers";
import { DocumentDetail } from "../pages/DocumentDetail";
import { DocumentChunks } from "../pages/DocumentChunks";
import { IngestionJob } from "../pages/IngestionJob";
import { Interview } from "../pages/Interview";
import { LandingPage } from "../pages/LandingPage";
import { Portfolio } from "../pages/Portfolio";
import { ProfileDocuments } from "../pages/ProfileDocuments";
import { ProjectDocuments } from "../pages/ProjectDocuments";
import { Projects } from "../pages/Projects";
import { PublicDemoSetting } from "../pages/PublicDemoSetting";
import { RecruiterAccess } from "../pages/RecruiterAccess";
import { TechnicalDocuments } from "../pages/TechnicalDocuments";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <LandingPage />,
  },
  {
    path: "/admin",
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
    path: "/admin/profile-documents",
    element: <ProfileDocuments />,
  },
  {
    path: "/admin/technical-documents",
    element: <TechnicalDocuments />,
  },
  {
    path: "/admin/users",
    element: <AdminUsers />,
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
    path: "/admin/jobs/:jobId",
    element: <IngestionJob />,
  },
  {
    path: "/admin/document-versions/:versionId/chunks",
    element: <DocumentChunks />,
  },
  {
    path: "/admin/access-grants",
    element: <AccessGrants />,
  },
  {
    path: "/admin/public-demo",
    element: <PublicDemoSetting />,
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
    path: "/interview",
    element: <Interview />,
  },
  {
    path: "*",
    element: <Navigate replace to="/" />,
  },
]);
