"""
Email notification service for sync job events
"""
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from sync_jobs.models import NotificationPreference, NotificationLog, SyncJob, SyncExecution
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending email notifications"""
    
    @staticmethod
    def send_job_completed_notification(job, execution):
        """Send notification when job completes successfully"""
        try:
            prefs = NotificationPreference.objects.get(user=job.created_by)
            if not prefs.email_enabled or not prefs.notify_on_job_completed:
                return
            
            email_address = prefs.email_address or job.created_by.email
            if not email_address:
                logger.warning(f"No email address for user {job.created_by.username}")
                return
            
            # Prepare email content
            from django.conf import settings
            site_url = getattr(settings, 'SITE_URL', 'http://localhost:8005')
            
            subject = f"Sync Job Completed: {job.name}"
            context = {
                'job': job,
                'execution': execution,
                'user': job.created_by,
                'site_url': site_url,
            }
            message = render_to_string('sync_jobs/emails/job_completed.html', context)
            text_message = render_to_string('sync_jobs/emails/job_completed.txt', context)
            
            # Send email
            send_mail(
                subject=subject,
                message=text_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email_address],
                html_message=message,
                fail_silently=False,
            )
            
            # Log notification
            NotificationLog.objects.create(
                user=job.created_by,
                notification_type='job_completed',
                job=job,
                execution=execution,
                email_sent=True,
                email_sent_at=timezone.now(),
            )
            
            logger.info(f"Sent completion notification for job {job.id} to {email_address}")
            
        except NotificationPreference.DoesNotExist:
            logger.debug(f"No notification preferences for user {job.created_by.username}")
        except Exception as e:
            logger.error(f"Error sending completion notification: {str(e)}", exc_info=True)
            # Log failed notification
            try:
                NotificationLog.objects.create(
                    user=job.created_by,
                    notification_type='job_completed',
                    job=job,
                    execution=execution,
                    email_sent=False,
                    error_message=str(e),
                )
            except:
                pass
    
    @staticmethod
    def send_job_failed_notification(job, execution):
        """Send notification when job fails"""
        try:
            prefs = NotificationPreference.objects.get(user=job.created_by)
            if not prefs.email_enabled or not prefs.notify_on_job_failed:
                return
            
            email_address = prefs.email_address or job.created_by.email
            if not email_address:
                return
            
            from django.conf import settings
            site_url = getattr(settings, 'SITE_URL', 'http://localhost:8005')
            
            subject = f"Sync Job Failed: {job.name}"
            context = {
                'job': job,
                'execution': execution,
                'user': job.created_by,
                'site_url': site_url,
            }
            message = render_to_string('sync_jobs/emails/job_failed.html', context)
            text_message = render_to_string('sync_jobs/emails/job_failed.txt', context)
            
            send_mail(
                subject=subject,
                message=text_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email_address],
                html_message=message,
                fail_silently=False,
            )
            
            NotificationLog.objects.create(
                user=job.created_by,
                notification_type='job_failed',
                job=job,
                execution=execution,
                email_sent=True,
                email_sent_at=timezone.now(),
            )
            
            logger.info(f"Sent failure notification for job {job.id} to {email_address}")
            
        except NotificationPreference.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Error sending failure notification: {str(e)}", exc_info=True)
    
    @staticmethod
    def send_schedule_missed_notification(job):
        """Send notification when scheduled job is missed"""
        try:
            prefs = NotificationPreference.objects.get(user=job.created_by)
            if not prefs.email_enabled or not prefs.notify_on_schedule_missed:
                return
            
            email_address = prefs.email_address or job.created_by.email
            if not email_address:
                return
            
            from django.conf import settings
            site_url = getattr(settings, 'SITE_URL', 'http://localhost:8005')
            
            subject = f"Scheduled Job Missed: {job.name}"
            context = {
                'job': job,
                'user': job.created_by,
                'site_url': site_url,
            }
            message = render_to_string('sync_jobs/emails/schedule_missed.html', context)
            text_message = render_to_string('sync_jobs/emails/schedule_missed.txt', context)
            
            send_mail(
                subject=subject,
                message=text_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email_address],
                html_message=message,
                fail_silently=False,
            )
            
            NotificationLog.objects.create(
                user=job.created_by,
                notification_type='schedule_missed',
                job=job,
                email_sent=True,
                email_sent_at=timezone.now(),
            )
            
        except Exception as e:
            logger.error(f"Error sending schedule missed notification: {str(e)}", exc_info=True)

