import { api } from "../api";
import { Status, useLoad } from "../components/common";
import { CourseCards } from "./Dashboard";

export default function Courses() {
  const { data, error } = useLoad(api.dashboard, []);
  if (!data) return <Status error={error} loading />;
  return (
    <>
      <h1>Courses</h1>
      <CourseCards data={data} />
    </>
  );
}
