from __future__ import annotations

from django.core.management.base import BaseCommand

from smartInterviewApp.models import Skill, normalize_skill_key


SKILLS = [
    ('Full Stack Development', 'Software Development', ['Full Stack', 'Fullstack', 'Full-stack Developer', 'Full Stack Developer']),
    ('JavaScript', 'Programming Language', ['JS', 'ECMAScript', 'ES6', 'Vanilla JavaScript']),
    ('Python', 'Programming Language', ['Python 3', 'Pytest', 'Python Programming', 'Python Scripting']),
    ('Core Java', 'Programming Language', ['Java', 'Java SE', 'OOP in Java', 'Collections', 'Exception Handling', 'Multithreading', 'JVM']),
    ('Spring Boot', 'Backend Development', ['Spring', 'Spring Framework', 'Spring MVC', 'Spring Data JPA', 'Spring Security']),
    ('React', 'Frontend Development', ['ReactJs', 'React.js', 'React JS', 'Frontend React', 'Hooks', 'Redux']),
    ('React Native', 'Mobile Development', ['ReactNative', 'Mobile app development', 'Mobile development']),
    ('Flutter', 'Mobile Development', ['Dart Flutter', 'Flutter app development', 'Cross platform mobile']),
    ('MongoDB', 'Database', ['Mongo DB', 'NoSQL', 'Document database']),
    ('MySQL', 'Database', ['My SQL', 'MySQL database']),
    ('REST API', 'Web Services', ['RESTful API', 'RESTful APIs', 'API integration', 'Web Services', 'Backend API', 'APIs', 'API Design', 'HTTP APIs', 'JSON API']),
    ('Node.js', 'Backend Development', ['Node', 'NodeJS', 'Express.js', 'Express', 'NPM', 'Node API']),
    ('PHP', 'Backend Development', ['Php']),
    ('Laravel', 'Backend Development', ['Laravel PHP']),
    ('HTML/CSS', 'Frontend Development', ['HTML', 'CSS', 'Responsive UI', 'Responsive design', 'Frontend UI']),
    ('Next.js', 'Frontend Development', ['NextJs', 'Next JS', 'Next.js framework']),
    ('Angular', 'Frontend Development', ['AngularJS', 'Angular 2+', 'RxJS', 'NgRx', 'Angular Material']),
    ('SQL', 'Database', ['Database Queries', 'Joins', 'Subqueries', 'Window Functions']),
    ('PostgreSQL', 'Database', ['Postgres', 'PostgreSQL joins']),
    ('Django', 'Backend Development', ['Django ORM', 'Python Django']),
    ('Django REST Framework', 'Backend Development', ['DRF', 'Django REST', 'Django API']),
    ('AWS', 'Cloud', ['Amazon Web Services', 'EC2', 'S3', 'Lambda', 'IAM', 'CloudWatch']),
    ('Docker', 'DevOps', ['Containers', 'Dockerfile', 'Docker Compose', 'Containerization']),
    ('Kubernetes', 'DevOps', ['K8s', 'Pods', 'Deployments', 'Services', 'Helm']),
    ('Git', 'Version Control', ['GitHub', 'GitLab', 'Version Control']),
    ('CI/CD', 'DevOps', ['Continuous Integration', 'Continuous Deployment', 'Build pipelines', 'Deployment pipeline']),
    ('Linux', 'Operating System', ['Unix', 'Shell scripting', 'Bash']),
    ('Salesforce', 'CRM', ['Salesforce CRM', 'Salesforce Developer', 'Salesforce Admin']),
    ('Apex', 'Salesforce', ['Salesforce Apex']),
    ('LWC', 'Salesforce', ['Lightning Web Components', 'Lightning Web Component']),
    ('SOQL', 'Salesforce', ['Salesforce Object Query Language']),
    ('Talent Acquisition', 'Human Resources', ['Recruitment', 'Hiring', 'Recruiting', 'Candidate Pipeline', 'Employer Branding', 'Recruitment Strategy']),
    ('Candidate Sourcing', 'Human Resources', ['Sourcing', 'Resume sourcing', 'Profile sourcing']),
    ('Candidate Screening', 'Human Resources', ['Screening Candidates', 'Resume screening', 'Profile screening']),
    ('Interview Coordination', 'Human Resources', ['Interview scheduling', 'Interview Coordination', 'Candidate coordination']),
    ('ATS', 'Human Resources', ['Applicant Tracking System', 'Naukri', 'LinkedIn Recruiter']),
    ('HR Recruitment', 'Human Resources', ['Recruiting', 'Recruitment', 'Hiring', 'Screening Candidates']),
    ('Communication Skills', 'Soft Skills', ['Communication', 'Verbal Communication', 'Written Communication', 'Stakeholder Communication']),
    ('SEO', 'Digital Marketing', ['Search Engine Optimization', 'On-page SEO', 'Off-page SEO']),
    ('Social Media Marketing', 'Digital Marketing', ['SMM', 'Social Media Campaigns', 'Social media management']),
    ('Campaign Management', 'Digital Marketing', ['Marketing campaigns', 'Ad campaigns', 'Campaign planning']),
    ('Content Writing', 'Digital Marketing', ['Copywriting', 'Content creation', 'Blog writing']),
    ('Google Analytics', 'Digital Marketing', ['GA4', 'Analytics reporting', 'Web analytics']),
    ('Lead Generation', 'Sales', ['Prospecting', 'Sales leads', 'Demand generation']),
    ('CRM', 'Sales', ['Customer Relationship Management', 'Salesforce CRM', 'HubSpot']),
    ('B2B Sales', 'Sales', ['Business to Business Sales', 'Enterprise sales']),
    ('Negotiation', 'Sales', ['Sales negotiation', 'Deal negotiation']),
    ('Tally', 'Accounting', ['Tally ERP', 'Tally Prime']),
    ('GST', 'Accounting', ['Goods and Services Tax', 'GST filing', 'GST returns']),
    ('Bookkeeping', 'Accounting', ['Accounting entries', 'Ledger maintenance']),
    ('Reconciliation', 'Accounting', ['Bank reconciliation', 'Account reconciliation']),
    ('Financial Reporting', 'Accounting', ['MIS reporting', 'Finance reports']),
    ('Customer Support', 'Customer Service', ['Customer Service', 'Customer care', 'Support tickets']),
    ('Operations Management', 'Operations', ['Operations', 'Process management', 'Operational coordination']),
]


class Command(BaseCommand):
    help = 'Seed the reusable interview skill taxonomy.'

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for name, category, aliases in SKILLS:
            _, was_created = Skill.objects.update_or_create(
                key=normalize_skill_key(name),
                defaults={
                    'name': name,
                    'category': category,
                    'aliases': aliases,
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(f'Seeded interview skills: {created} created, {updated} updated.'))
